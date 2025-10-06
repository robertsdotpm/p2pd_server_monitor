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
from fastapi import FastAPI, Request, HTTPException, Depends, Body
from p2pd import *
from typing_extensions import TypedDict
from typing import Any, List, Optional
from pydantic import BaseModel
from .dealer_utils import *
from .db_init import *
from .dealer_work import *
from .txt_strs import *
from .mem_schema import *
from .do_imports import *

app = FastAPI(default_response_class=PrettyJSONResponse)

db = MemSchema()
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
    is_success: bool
    t: int

class Statuses(BaseModel):
    statuses: List[StatusItem]

class AliasUpdate(BaseModel):
    alias_id: int
    ip: str
    current_time: int | None = None

"""
class WorkRequest(BaseModel):
    stack_type: Optional[int | None] = DUEL_STACK
    current_time: Optional[int] = None
    monitor_frequency: Optional[int] = MONITOR_FREQUENCY
    table_type: Optional[int | None] = None
"""

class WorkRequest(BaseModel):
    stack_type: int | None
    table_type: int | None
    current_time: int | None
    monitor_frequency: int | None

async def refresh_server_cache():
    global server_cache
    while True:
        # Init server list.
        s = {}
        for service_type in SERVICE_TYPES:
            s[service_type] = {}
            for af in VALID_AFS:
                s[service_type][af] = {}
                for proto in (UDP, TCP,):
                    s[service_type][af][proto] = []

        # This doesnt work since it doesnt take into account groups.
        for status_id in db.statuses:
            # Look at statuses for services imported.
            status = db.statuses[status_id]
            table_type = status["table_type"]
            if table_type != SERVICES_TABLE_TYPE:
                continue

            # Compute score for service.
            score = compute_service_score(status)
            row_id = status["row_id"]
            row = db.records[table_type][row_id]
            row["score"] = score
            for k in ("uptime", "max_uptime", "last_success",):
                row[k] = status[k]

            # Record row in right category.
            service_type = row["type"]
            af = row["af"]
            proto = row["proto"]
            s[service_type][af][proto].append(row)


        for service_type in SERVICE_TYPES:
            for af in VALID_AFS:
                for proto in (UDP, TCP,):
                    s[service_type][af][proto].sort(key=lambda x: x["score"])

        s["timestamp"] = int(time.time())
        server_cache = s
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
    
    print(request.stack_type)
    print(current_time)
    print(monitor_frequency)
    print(table_type)

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

            if service.alias_id:
                alias_count += 1

        # STUN change servers should have all or no alias.
        if records[0]["type"] == STUN_CHANGE_TYPE:
            if alias_count not in (0, 4):
                # TODO: delete created records
                raise Exception("STUN change servers need even aliases")

        db.add_work(records[0]["af"], SERVICES_TABLE_TYPE, records)

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
    alias["ip"] = ip

    for table_type in (IMPORTS_TABLE_TYPE, SERVICES_TABLE_TYPE):
        db.update_table_ip(table_type, ip, alias_id, current_time)

    return [alias_id]


@app.get("/list_aliases_len")
async def list_aliases_len():
    return len(db.records[ALIASES_TABLE_TYPE])

@app.get("/list_aliases")
async def list_aliases_len():
    return db.records[ALIASES_TABLE_TYPE]

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