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

    having to load all the dns names before imports for IPs is very slow
    maybe i should cache this somehow

    figure out how to get stdout for worker processes logged

    could make a change to work allocat1on to force complet1on of
    al1as work f1rst before hand1ng out 1mports or serv1ce work. then
    just remove the al1as resolv stuff before 1mports.
        -- move it to the clients -- make it choose alias work, keep looping until
        no work, then sleep for N, before resuming regular work (no specification)

    -- cleanup that status_id update logic since you always seem to want to do
    that in all cases?

    -- theres no port in the server results
    -- make it so you can run do_imports multiple times and it wont interfer with
    existing records
    -- time work and sleep if its too fast -- theres locking errors on aliases rn
    since the work finishes too fast
        -- sleep for rand secs so it spreads out
        -- add other tricks for database locks
            -- if db lock on /work catch exception and return special status to client
            so client knows to retry after a delay
                -- theres no validation of server out and if it errors the
                clients just go into a spam loop
    -- inital /server results some have quality score set to 0

    I think I could refactor this whole thing to use in-memory databases
    
"""

import uvicorn
import ast
import aiosqlite
import sqlite3
from fastapi import FastAPI, Request, HTTPException, Depends
from p2pd import *
from .dealer_utils import *
from .db_init import *
from .dealer_work import *
from .txt_strs import *
from .mem_schema import *

app = FastAPI(default_response_class=PrettyJSONResponse)

db = MemSchema()
server_cache = []
refresh_task = None

async def refresh_server_cache():
    global server_cache
    while True:
        try:
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
        except sqlite3.OperationalError:
            pass

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
            #await insert_imports_test_data(db)
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
def get_work(stack_type=DUEL_STACK, current_time=None, monitor_frequency=MONITOR_FREQUENCY, table_type=None):
    # Indicate IPv4 / 6 support of worker process.
    if stack_type == DUEL_STACK:
        need_afs = VALID_AFS
    else:
        need_afs = (stack_type,) if stack_type in VALID_AFS else VALID_AFS

    # Set table type.
    if table_type in TABLE_TYPES:
        table_types = (table_type,)
    else: 
        table_types = TABLE_TYPES

    # Get oldest work by table type and client AF preference.
    current_time = current_time or int(time.time())
    for table_choice in table_types:
        for need_af in need_afs:
            """
            The most recent items are always added at the end. Items at the start
            are oldest. If the oldest items are still too recent to pass time
            checks then we know that later items in the queue are also too recent.
            """
            wq = db.work[table_choice][need_af]
            for status_type in (STATUS_INIT, STATUS_AVAILABLE, STATUS_DEALT,):
                for group_id, meta_group in wq.queues[status_type]:
                    assert(meta_group)
                    group = meta_group["group"]

                    # Never been allocated so safe to hand out.
                    if status_type == STATUS_INIT:
                        wq.move_work(group_id, STATUS_DEALT)
                        return group

                    # Work is moved back to available but don't do it too soon.
                    # Statuses are bulk updated for entries in a group.
                    status = db.statuses[group[0]["status_id"]]
                    elapsed = current_time - status["last_status"]
                    if status_type != STATUS_DEALT:
                        if elapsed < monitor_frequency:
                            break

                    # Check for worker timeout.
                    if status_type == STATUS_DEALT:
                        if elapsed < WORKER_TIMEOUT:
                            break

                    # Otherwise: allocate it as work.
                    wq.move_work(group_id, STATUS_DEALT)
                    return group

    return []

# Worker processes check in to signal status of work.
@app.get("/complete", dependencies=[Depends(localhost_only)])
def signal_complete_work(statuses):
    # Return list of updated status IDs.
    results = []

    # Convert dict string back to Python.
    statuses = ast.literal_eval(statuses)
    for status_info in statuses:
        ret = db.mark_complete(**status_info)
        results.append(ret)
    
    return results

@app.get("/insert", dependencies=[Depends(localhost_only)])
def insert_services(imports_list, status_id):
    # Convert dict string back to Python.
    imports_list = ast.literal_eval(imports_list)
    for groups in imports_list:
        records = []
        alias_count = 0
        for service in groups:
            record = db.insert_service(**service)
            records.append(record)

            if service["alias_id"]:
                alias_count += 1

        # STUN change servers should have all or no alias.
        if records[0]["type"] == STUN_CHANGE_TYPE:
            if alias_count not in (0, 4,):
                # TODO: delete created records.
                raise Exception("STUN change servers need even aliases")

        db.add_work(records[0]["af"], SERVICES_TABLE_TYPE, records)

    # Only allocate imports work once.
    # This deletes the associated status record. 
    db.mark_complete(
        1 if len(imports_list) else 0,
        int(status_id)
    )

    return []

@app.get("/alias", dependencies=[Depends(localhost_only)])
def update_alias(alias_id, ip, current_time=None):
    ip = ensure_ip_is_public(ip)
    current_time = current_time or int(time.time())
    if alias_id not in db.records[ALIASES_TABLE_TYPE]:
        return []

    # Update IP for the alias entry.
    alias = db.records[ALIASES_TABLE_TYPE][alias_id]
    alias["ip"] = ip

    for table_type in (IMPORTS_TABLE_TYPE, SERVICES_TABLE_TYPE,):
        db.update_table_ip(table_type, ip, alias_id, current_time)

    return [alias_id]

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