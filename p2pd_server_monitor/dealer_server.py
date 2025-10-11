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


    overview:
    - I insert a bunch of STUN map servers
        - any record that is associated with a FQN gets an alias
    - Aliases are input as records
    - All records have a status
        - Aliases, imports, and services
    - When aliases are updated the update should
        - update the alias record
        - update the IP for the import and services record.
    - dont write tests that depend on other processes to run because they're
    not deterministic and too hard to verify -- do it all with data structs

    Ideas for new tests to write:
    - store a list of fqn: ip mappings and update them.
        - then check associated records have aliases set
        - do this using the alias_update api
    


"""


import uvicorn
import aiosqlite
from fastapi import FastAPI, Depends
from p2pd import *
from typing import List
from .dealer_utils import *
from .db_init import *
from .txt_strs import *
from .mem_db_utils import *
from .mem_db import *
from .do_imports import *

app = FastAPI(default_response_class=PrettyJSONResponse)
mem_db = MemDB()
server_cache = []
refresh_task = None

async def refresh_server_cache():
    global server_cache
    global mem_db
    while True:
        server_cache = build_server_list(mem_db)
        async with aiosqlite.connect(DB_NAME) as sqlite_db:
            async with sqlite_db.execute("BEGIN"):
                await delete_all_data(sqlite_db)
                await sqlite_export(mem_db, sqlite_db)

        await sqlite_db.commit()
        await asyncio.sleep(60)

@app.on_event("startup")
async def main():
    global refresh_task
    global mem_db
    await sqlite_import(mem_db)
    refresh_task = asyncio.create_task(refresh_server_cache())

# Hands out work (servers to check) to worker processes.
@app.post("/work", dependencies=[Depends(localhost_only)])
def api_get_work(request: GetWorkReq):
    stack_type = request.stack_type
    current_time = request.current_time or int(time.time())
    monitor_frequency = request.monitor_frequency or MONITOR_FREQUENCY
    table_type = request.table_type

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

    # Allocate work from work queues based on req preferences.
    return mem_db.allocate_work(
        need_afs,
        table_types,
        current_time,
        monitor_frequency
    )

@app.post("/complete", dependencies=[Depends(localhost_only)])
def api_work_done(payload: WorkDoneReq):
    results: List[int] = []
    for status_info in payload.statuses:
        ret = mem_db.mark_complete(**status_info.dict())
        results.append(ret)

    return results

@app.post("/insert", dependencies=[Depends(localhost_only)])
def api_insert_services(payload: InsertServicesReq):
    for groups in payload.imports_list:
        records = []
        alias_count = 0
        for service in groups:
            # Convert Pydantic model to dict
            record = mem_db.insert_service(**service.dict())
            records.append(record)

            if service.alias_id is not None:
                alias_count += 1

        # STUN change servers should have all or no alias.
        if records[0].type == STUN_CHANGE_TYPE:
            if alias_count not in (0, 4):
                # TODO: delete created records
                raise Exception("STUN change servers need even aliases")

        mem_db.add_work(records[0].af, SERVICES_TABLE_TYPE, records)

    # Only allocate imports work once.
    # This deletes the associated status record. 
    mem_db.mark_complete(
        1 if len(payload.imports_list) else 0,
        payload.status_id
    )

    return []

@app.post("/alias", dependencies=[Depends(localhost_only)])
def api_update_alias(data: AliasUpdateReq):
    ip = ensure_ip_is_public(data.ip)
    current_time = data.current_time or int(time.time())
    alias_id = data.alias_id

    if alias_id not in db.records[ALIASES_TABLE_TYPE]:
        raise Exception("Alias id not found.")
    
    alias = mem_db.records[ALIASES_TABLE_TYPE][alias_id]
    alias.ip = ip

    for table_type in (IMPORTS_TABLE_TYPE, SERVICES_TABLE_TYPE):
        mem_db.update_table_ip(table_type, ip, alias_id, current_time)

    return []

# Show a listing of servers based on quality
# Only public API is this one.
@app.get("/servers")
async def api_list_servers():
    return server_cache

if IS_DEBUG:
    exec(open("dealer_test_apis.py").read(), globals())

if __name__ == "__main__":
    uvicorn.run(
        "p2pd_server_monitor.dealer_server:app",
        host="*",
        port=8000,
        reload=False
    )