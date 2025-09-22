"""
I'll put notes here.

Priority:
    -- seems to be a bug where adding logging causes code not to run, def need to not skip writing unit tests at the end of all this
    
    -- unit tests.
    -- wll use pub bind for fastapi and for private calls reject non-local client src.
    add auth later on7
    -- integration
    -- publish

-- then actually process all ips and service types to import for the DB (boring)

future:
    --exp backoff based on service downtime
    avoid having all the checks occur at the same time even if the threshold is met
    - i think the issue is all files that import P2PD use the same log file path and
    cant write to it if they are different processes -- maybe update this
    -- technically A and AAA dns can map to a list of IPs so my data structure for
    aliases are wrong but lets roll with it to start with since its simple.
    -- some servers have additional meta data like even PNP has oub keys and turn
    has realms?
    -- some dns servers return different ips each time. do you want ips to change
    for servers? a dns might represent a cluster. maybe still works depending
    on the protocol.

edge case:
    For STUN change servers if you use an alias you need different aliases for both
    primary and change IPs OR no aliases. a single alias means that the pair will
    break on DNS IP updates.
    - negative uptimes possible if time manually set in the past but this is
    still useful for tests and these APIs wont be public
"""

import uvicorn
import asyncio
import ast
import aiosqlite
from typing import Union, Any
from fastapi import FastAPI
import json
import math
from p2pd import *
from .dealer_utils import *
from .db_init import *
from .dealer_work import *

app = FastAPI(default_response_class=PrettyJSONResponse)

@app.on_event("startup")
async def main():
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await delete_all_data(db)
            await init_settings_table(db)
            await insert_imports_test_data(db)
            await db.commit()
        except:
            what_exception()

# Hands out work (servers to check) to worker processes.
@app.get("/work")
async def get_work(stack_type=DUEL_STACK, current_time=None, monitor_frequency=MONITOR_FREQUENCY):
    # Indicate IPv4 / 6 support of worker process.
    if stack_type == DUEL_STACK:
        need_af = "%"
    else:
        need_af = stack_type if stack_type in VALID_AFS else "%"

    print("in get work")

    # Connect to DB and find some work.
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Fetch all status rows, oldest first
        sql = "SELECT * FROM status ORDER BY last_status ASC"
        async with db.execute(sql) as cursor:
            status_entries = [dict(r) for r in await cursor.fetchall()]

        print("status entries = ", status_entries)

        
        # Get a group of service(s), aliases, or imports.
        # Check if its allocatable, mark it allocated, and return it.
        current_time = current_time or int(time.time())
        for status_entry in status_entries:
            group_records = await fetch_group_records(db, status_entry, need_af)
            allocatable_records = check_allocatable(
                group_records,
                current_time,
                monitor_frequency
            )

            if allocatable_records:
                # Atomically claim the group
                claimed = await claim_group(db, group_records, current_time)
                if claimed:
                    return allocatable_records
        
    return []

# Worker processes check in to signal status of work.
@app.get("/complete")
async def signal_complete_work(statuses):
    # Convert dict string back to Python.
    statuses = ast.literal_eval(statuses)

    # Return list of updated status IDs.
    results = []
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Split into a function so it can be using inside a transaction
        # by the imports method (doesn't call commit on its own.)
        async with db.execute("BEGIN"):
            for status_info in statuses:
                status_info["db"] = db
                ret = await mark_complete(**status_info)
                results.append(ret)

            # Save all changes as atomic TX.
            await db.commit()

    return results

#Show a listing of servers based on quality
@app.get("/servers")
async def list_servers():
    servers = {}
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Server listing per service type.
        for service_type in SERVICE_TYPES:
            servers[service_type] = {}

            # Sub-divided by transport support.
            for proto in (UDP, TCP,):
                servers[service_type][proto] = {}

                # Then by address family supported.
                for af in VALID_AFS:
                    sql = """
                    SELECT *
                    FROM service_quality
                    WHERE type = ? 
                    AND proto = ? 
                    AND af = ?
                    ORDER BY group_score DESC, service_id ASC;
                    """
                    params = (service_type, proto, af,)
                    async with db.execute(sql, params) as cursor:
                        rows = [dict(r) for r in await cursor.fetchall()]

                    # Assign the list of groups to the nested structure
                    servers[service_type][proto][af] = rows

    return servers

@app.get("/alias")
async def update_alias(alias_id: int, ip: str):
    ip = ensure_ip_is_public(ip)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("BEGIN"):
            # Update IP for the alias entry.
            sql = "UPDATE aliases SET ip = ? WHERE id = ?"
            await db.execute(sql, (ip, alias_id,))

            # Every record pointing to the alias also update their IP.
            for table_name in ("imports", "services"):
                sql = f"UPDATE {table_name} SET ip = ? WHERE alias_id = ?"
                await db.execute(sql, (ip, alias_id,))

            await db.commit()

    return [alias_id]

@app.get("/insert")
async def insert_services(imports_list, status_id):
    # Convert dict string back to Python.
    imports_list = ast.literal_eval(imports_list)
    print("imports list = ", type(imports_list), " ", imports_list)
    print("imports list [0] = ", type(imports_list[0]))

    # DB connection for sqlite.
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Create list of group IDs for each service(s) list.
        group_ids = []
        for _ in imports_list:
            group_id = await get_new_group_id(db)
            group_ids.append(group_id)

        # Single atomic transaction for all inserts, dels, etc.
        async with db.execute("BEGIN"):
            for services in imports_list:
                print("services = ", type(services), services)

                # All inserts happen in the same transaction.
                group_id = group_ids.pop(0)
                for service in services:
                    service["group_id"] = group_id
                    service["db"] = db
                    await insert_service(**service)

            # Only allocate imports work once.
            # This deletes the associated status record. 
            await mark_complete(
                db,
                1 if len(imports_list) else 0,
                int(status_id),
                int(time.time())
            )

            # Commit all changes at once.
            await db.commit()

if __name__ == "__main__":
    uvicorn.run(
        "p2pd_server_monitor.dealer_server:app",
        host="127.0.0.1",
        port=8000,
        reload=False
    )