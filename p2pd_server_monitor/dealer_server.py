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
    
    dont worry about saving state yet for first version. if clients see an empty
    server list they can avoid update. otherwise a fresh reload is equivalent to
    having a success list for all servers tho you lose the uptime and scoring info
    
    
    
"""

import uvicorn
import ast
from fastapi import FastAPI, Request, HTTPException, Depends, Body
from p2pd import *
from typing_extensions import TypedDict
from typing import Any, List, Optional
from pydantic import BaseModel
from .dealer_utils import *
from .db_init import *
from .dealer_work import *
from .txt_strs import *
from .mem_db import *
from .do_imports import *

app = FastAPI(default_response_class=PrettyJSONResponse)

db = MemDB()
server_cache = []
refresh_task = None

class Service(BaseModel):
    service_type: int
    af: int
    proto: int
    ip: str
    port: int
    user: str | None
    password: str | None
    alias_id: int | None
    score: int

class InsertPayload(BaseModel):
    imports_list: List[List[Service]]
    status_id: int

class StatusItem(BaseModel):
    status_id: int
    is_success: int
    t: int

class Statuses(BaseModel):
    statuses: List[StatusItem]

class AliasUpdate(BaseModel):
    alias_id: int
    ip: str
    current_time: int | None = None

class WorkRequest(BaseModel):
    stack_type: int | None
    table_type: int | None
    current_time: int | None
    monitor_frequency: int | None

def build_server_list():
    # Init server list.
    s = {}
    for service_type in SERVICE_TYPES:
        by_service = s[TXTS[service_type]] = {}
        for af in VALID_AFS:
            by_af = by_service[TXTS["af"][af]] = {}
            for proto in (UDP, TCP,):
                by_proto = by_af[TXTS["proto"][proto]] = []


    for group_id in db.groups:
        meta_group = db.groups[group_id]
        if meta_group.table_type != SERVICES_TABLE_TYPE:
            continue

        scores = []
        group = group_to_dict(meta_group.group)
        for record in group:
            status = db.statuses[record["status_id"]].dict()
            for k in ("uptime", "max_uptime", "last_success",):
                record[k] = status[k]

            record["score"] = compute_service_score(status)
            scores.append(record["score"])

        score_avg = sum(scores) / len(scores)
        for record in group:
            record["score"] = score_avg

        service_type = TXTS[group[0]["type"]]
        af = TXTS["af"][group[0]["af"]]
        proto = TXTS["proto"][group[0]["proto"]]
        s[service_type][af][proto].append(group)

    for service_type in SERVICE_TYPES:
        for af in VALID_AFS:
            for proto in (UDP, TCP,):
                by_service = s[TXTS[service_type]]
                by_af = by_service[TXTS["af"][af]]
                by_proto = by_af[TXTS["proto"][proto]]
                by_proto.sort(key=lambda x: x[0]["score"])

    s["timestamp"] = int(time.time())
    return s

async def refresh_server_cache():
    global server_cache
    while True:
        server_cache = build_server_list()
        await asyncio.sleep(60)

@app.on_event("startup")
async def main():
    global refresh_task
    insert_main(db)
    refresh_task = asyncio.create_task(refresh_server_cache())

def localhost_only(request: Request):
    client_host = request.client.host
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Access forbidden")

@app.get("/list_groups")
async def list_groups():
    return db.groups
    
@app.get("/concurrency_test", dependencies=[Depends(localhost_only)])
async def concurrency_test():
    # Wait for alias work to be done.
    print("Waiting for alias work to be done.")
    while 1:
        still_set = False
        for status_type in (STATUS_INIT, STATUS_AVAILABLE,):
            for af in VALID_AFS:
                q = db.work[ALIASES_TABLE_TYPE][af].queues[status_type]
                if len(q):
                    still_set = True
                    print(af, " ", status_type, " ", len(q))

        if not still_set:
            break

        await asyncio.sleep(0.1)

    print("All aliases processed.")



# Hands out work (servers to check) to worker processes.
@app.post("/work", dependencies=[Depends(localhost_only)])
def get_work(request: WorkRequest):
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

    # Get oldest work by table type and client AF preference.
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
                    group = meta_group.group

                    # Never been allocated so safe to hand out.
                    if status_type == STATUS_INIT:
                        wq.move_work(group_id, STATUS_DEALT)
                        return group_to_dict(group)

                    # Work is moved back to available but don't do it too soon.
                    # Statuses are bulk updated for entries in a group.
                    status = db.statuses[group[0].status_id]
                    elapsed = current_time - status.last_status
                    if status_type != STATUS_DEALT:
                        if elapsed < monitor_frequency:
                            break

                    # Check for worker timeout.
                    if status_type == STATUS_DEALT:
                        if elapsed < WORKER_TIMEOUT:
                            break

                    # Otherwise: allocate it as work.
                    wq.move_work(group_id, STATUS_DEALT)
                    return group_to_dict(group)

    return []

@app.post("/complete", dependencies=[Depends(localhost_only)])
def signal_complete_work(payload: Statuses):
    results: List[int] = []
    for status_info in payload.statuses:
        ret = db.mark_complete(**status_info.dict())
        results.append(ret)

    return results

@app.post("/insert", dependencies=[Depends(localhost_only)])
def insert_services(payload: InsertPayload):
    for groups in payload.imports_list:
        records = []
        alias_count = 0
        for service in groups:
            # Convert Pydantic model to dict
            record = db.insert_service(**service.dict())
            records.append(record)

            if service.alias_id is not None:
                alias_count += 1

        # STUN change servers should have all or no alias.
        if records[0].type == STUN_CHANGE_TYPE:
            if alias_count not in (0, 4):
                # TODO: delete created records
                raise Exception("STUN change servers need even aliases")

        db.add_work(records[0].af, SERVICES_TABLE_TYPE, records)

    # Only allocate imports work once.
    # This deletes the associated status record. 
    db.mark_complete(
        1 if len(payload.imports_list) else 0,
        payload.status_id
    )

    return []

@app.post("/alias", dependencies=[Depends(localhost_only)])
def update_alias(data: AliasUpdate):
    ip = ensure_ip_is_public(data.ip)
    current_time = data.current_time or int(time.time())
    alias_id = data.alias_id

    if alias_id not in db.records[ALIASES_TABLE_TYPE]:
        raise Exception("Alias id not found.")
    
    alias = db.records[ALIASES_TABLE_TYPE][alias_id]
    alias.ip = ip

    for table_type in (IMPORTS_TABLE_TYPE, SERVICES_TABLE_TYPE):
        db.update_table_ip(table_type, ip, alias_id, current_time)

    return []

@app.get("/list_aliases_len")
async def list_aliases_len():
    return len(db.records[ALIASES_TABLE_TYPE])

@app.get("/list_aliases")
async def list_aliases_len():
    return db.records[ALIASES_TABLE_TYPE]


@app.get("/sql_export", dependencies=[Depends(localhost_only)])
async def sql_export():
    await db.sqlite_export()
    return "done"

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