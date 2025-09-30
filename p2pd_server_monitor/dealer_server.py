"""
I'll put notes here.

Priority:
    -- add a list of servers
    -- integration
    -- merge and publish

future:
    -- technically A and AAA dns can map to a list of IPs so my data structure for
    aliases are wrong but lets roll with it to start with since its simple.
    -- some servers have additional meta data like even PNP has oub keys and turn
    has realms?
    -- some dns servers return different ips each time. do you want ips to change
    for servers? a dns might represent a cluster. maybe still works depending
    on the protocol.

    -- cleanup ideas:
        -- delete old rows that havent been updated in a while
        -- dont delete import on complete -- disable it

edge case:
    - negative uptimes possible if time manually set in the past but this is
    still useful for tests and these APIs wont be public
"""

import uvicorn
import ast
import aiosqlite
from fastapi import FastAPI, Request, HTTPException, Depends
from p2pd import *
from .dealer_utils import *
from .db_init import *
from .dealer_work import *
from .txt_strs import *

app = FastAPI(default_response_class=PrettyJSONResponse)

server_cache = []
refresh_task = None

async def refresh_server_cache():
    global server_cache
    while True:
        servers = {}
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row

            # Server listing per service type.
            for service_type in SERVICE_TYPES:
                per_type = servers[TXTS[service_type]] = {}
                
                # Sub-divided by transport support.
                for proto in (UDP, TCP,):
                    per_proto = per_type[TXTS["proto"][proto]] = {}

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
                        per_af = per_proto[TXTS["af"][af]] = rows

        if servers:
            server_cache = servers

        server_cache["last_refresh"] = int(time.time())
        await asyncio.sleep(60)

@app.on_event("startup")
async def main():
    global refresh_task
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous = 1;")
        await db.execute('PRAGMA busy_timeout = 5000') # Wait up to 5 seconds
        await db.commit()
        try:
            #await delete_all_data(db)
            await init_settings_table(db)
            await insert_imports_test_data(db)
            await db.commit()
        except:
            what_exception()
    
    refresh_task = asyncio.create_task(refresh_server_cache())

def localhost_only(request: Request):
    client_host = request.client.host
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Access forbidden")

# Hands out work (servers to check) to worker processes.
@app.get("/work", dependencies=[Depends(localhost_only)])
async def get_work(stack_type=DUEL_STACK, current_time=None, monitor_frequency=MONITOR_FREQUENCY):
    # Indicate IPv4 / 6 support of worker process.
    if stack_type == DUEL_STACK:
        need_af = "%"
    else:
        need_af = stack_type if stack_type in VALID_AFS else "%"

    # Connect to DB and find some work.
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("BEGIN IMMEDIATE"):
            # Fetch all status rows, oldest first
            sql = "SELECT * FROM status WHERE status != ? ORDER BY last_status ASC"
            async with db.execute(sql, (STATUS_DISABLED,)) as cursor:
                status_entries = [dict(r) for r in await cursor.fetchall()]

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
                        await db.commit()
                        return allocatable_records
        
    return []

# Worker processes check in to signal status of work.
@app.get("/complete", dependencies=[Depends(localhost_only)])
async def signal_complete_work(statuses):
    # Return list of updated status IDs.
    results = []

    # Convert dict string back to Python.
    statuses = ast.literal_eval(statuses)
    #print(statuses)

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

@app.get("/alias", dependencies=[Depends(localhost_only)])
async def update_alias(alias_id, ip, current_time=None):
    ip = ensure_ip_is_public(ip)
    current_time = current_time or int(time.time())
    params = (ip, alias_id, current_time, MAX_SERVER_DOWNTIME * 2,)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("BEGIN"):
            # Update IP for the alias entry.
            alias_sql = "UPDATE aliases SET ip = ? WHERE id = ?"
            await db.execute(alias_sql, (ip, alias_id,))

            # Every record pointing to the alias also update their IP.
            for table_name in ("imports", "services"):
                main_sql = f"""
                UPDATE {table_name} SET ip = ?
                WHERE alias_id = ?
                AND EXISTS (
                    SELECT 1
                    FROM status
                    WHERE status.row_id = {table_name}.id
                    AND status.status != {STATUS_DISABLED}
                    AND (
                        (
                            status.last_success = 0
                            AND status.last_uptime = 0
                            AND status.test_no >= 2
                        )
                        OR
                        (
                            status.last_success != 0
                            AND (? - status.last_uptime) > ?
                        )
                    )
                );
                """
                await db.execute(main_sql, params)

            await db.commit()

    return [alias_id]

@app.get("/insert", dependencies=[Depends(localhost_only)])
async def insert_services(imports_list, status_id):
    # Convert dict string back to Python.
    imports_list = ast.literal_eval(imports_list)

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
                alias_count = 0

                # All inserts happen in the same transaction.
                group_id = group_ids.pop(0)
                for service in services:
                    service["group_id"] = group_id
                    service["db"] = db
                    if service["alias_id"]:
                        alias_count += 1
                        
                    await insert_service(**service)

                # STUN change servers should have all or no alias.
                if services[0]["service_type"] == STUN_CHANGE_TYPE:
                    if alias_count not in (0, 4,):
                        raise Exception("STUN change servers need even aliases")

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

# Show a listing of servers based on quality
# Only public API is this one.
@app.get("/servers")
async def list_servers():
    return server_cache

if __name__ == "__main__":
    uvicorn.run(
        "p2pd_server_monitor.dealer_server:app",
        host="*",
        port=8000,
        reload=False
    )