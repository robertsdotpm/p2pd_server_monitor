import math
import time
import json
from fastapi.responses import JSONResponse
from fastapi import Request, HTTPException
from p2pd import *
from .db_init import *
from .dealer_defs import *
from .txt_strs import *

def localhost_only(request: Request):
    client_host = request.client.host
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Access forbidden")

class PrettyJSONResponse(JSONResponse):
    def render(self, content: any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,        # pretty-print here
        ).encode("utf-8")

def compute_service_score(status, max_uptime_override=None):
    failed_tests = float(status.get("failed_tests", 0))
    test_no = float(status.get("test_no", 0))
    uptime = float(status.get("uptime", 0))

    if max_uptime_override is None:
        max_uptime = float(status.get("max_uptime", 0))
    else: 
        max_uptime = float(max_uptime_override)
    
    # Avoid division by zero
    uptime_ratio = (uptime / max_uptime) if max_uptime > 0 else 0.0
    uptime_ratio = min(max(uptime_ratio, 0.0), 1.0)
    quality_score = (
        (1.0 - failed_tests / (test_no + 1e-9)) * 
        (0.5 * uptime_ratio + 0.5) *
        (1.0 - math.exp(-test_no / 50.0))
    )
    
    return quality_score

def get_fqn_list(mem_db, ip):
    if ip is None:
        return []
    
    fqns = set()
    if ip in mem_db.aliases_by_ip:
        for alias in mem_db.aliases_by_ip[ip]:
            if alias.fqn is not None:
                fqns.add(alias.fqn)

    return list(fqns)[::-1]

def build_server_list(mem_db):
    # Init server list.
    s = {}
    for service_type in SERVICE_TYPES:
        by_service = s[TXTS[service_type]] = {}
        for af in VALID_AFS:
            by_af = by_service[TXTS["af"][af]] = {}
            for proto in (UDP, TCP,):
                by_proto = by_af[TXTS["proto"][proto]] = []


    for group_id in mem_db.groups:
        meta_group = mem_db.groups[group_id]
        if meta_group.table_type != SERVICES_TABLE_TYPE:
            continue

        scores = []
        group = list_x_to_dict(meta_group.group)
        for record in group:
            status = mem_db.statuses[record["status_id"]].dict()
            for k in ("uptime", "max_uptime", "last_success",):
                record[k] = status[k]

            record["score"] = compute_service_score(status)
            record["fqns"] = get_fqn_list(mem_db, record["ip"])
            scores.append(record["score"])

        if len(scores):
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
                by_proto.sort(key=lambda x: x[0]["score"], reverse=True)

    s["timestamp"] = int(time.time())
    return s

def mark_complete(mem_db, is_success: int, status_id: int, t=None):
    t = t or int(time.time())
    status_type = STATUS_AVAILABLE
    if status_id not in mem_db.statuses:
        raise KeyError("could not load status row %s" % (status_id,))
    
    # Delete target row if status is for an imports.
    # We only want imports work to be done once.
    status = mem_db.statuses[status_id]
    table_type = status.table_type
    if table_type == IMPORTS_TABLE_TYPE:
        if status.test_no >= IMPORT_TEST_NO:
            status_type = STATUS_DISABLED
        if is_success:
            status_type = STATUS_DISABLED

    # Remove from dealt queue.
    record = mem_db.records[table_type][status.row_id]
    af = record.af
    group_id = record.group_id

    # Try to move work to available -- throw exception if not exist.
    mem_db.work[table_type][af].move_work(group_id, status_type)

    # Update stats for success.
    if is_success:
        if not status.last_uptime:
            change = 0
        else:
            change = max(0, t - status.last_uptime)

        status.uptime += change
        if status.uptime > status.max_uptime:
            status.max_uptime = status.uptime

        status.last_uptime = t
        status.last_success = t

    # Update stats for failure.
    if not is_success:
        status.failed_tests += 1
        status.uptime = 0
    
    status.status = status_type
    status.test_no += 1
    status.last_status = t

def allocate_work(mem_db, need_afs, table_types, cur_time, mon_freq):
    # Get oldest work by table type and client AF preference.
    for table_choice in table_types:
        for need_af in need_afs:
            """
            The most recent items are always added at the end. Items at the start
            are oldest. If the oldest items are still too recent to pass time
            checks then we know that later items in the queue are also too recent.
            """
            wq = mem_db.work[table_choice][need_af]
            for status_type in (STATUS_INIT, STATUS_AVAILABLE, STATUS_DEALT,):
                for group_id, meta_group in wq.queues[status_type]:
                    group = meta_group.group

                    # Never been allocated so safe to hand out.
                    if status_type == STATUS_INIT:
                        wq.move_work(group_id, STATUS_DEALT)
                        return list_x_to_dict(group)

                    # Work is moved back to available but don't do it too soon.
                    # Statuses are bulk updated for entries in a group.
                    work_timestamp = wq.timestamps[group_id]
                    elapsed = cur_time - work_timestamp
                    if not work_timestamp or elapsed < 0:
                        # Sanity check to avoid invalid results.
                        continue

                    # In time order with oldest first.
                    # So if this isn't old enough then none are.
                    if status_type != STATUS_DEALT:
                        if elapsed < mon_freq:
                            break

                    # Check for worker timeout.
                    if status_type == STATUS_DEALT:
                        if elapsed < WORKER_TIMEOUT:
                            break

                    # Otherwise: allocate it as work.
                    wq.move_work(group_id, STATUS_DEALT)
                    return list_x_to_dict(group)
                
    return []

def update_table_ip(mem_db, table_type: int, ip: str, alias_id: int, current_time: int):
    for record in mem_db.records_by_aliases[alias_id]:
        # Skip records that don't match the table type.
        if record.table_type != table_type:
            continue

        # SKip disabled records.
        status = mem_db.statuses[record.status_id]
        if status.status == STATUS_DISABLED:
            continue

        # 1) If current IP is invalid set new IP.
        try:
            ensure_ip_is_public(record.ip)
        except:
            record.ip = ip
            continue

        # 2) If import and its never been checked set new IP.
        if table_type == IMPORTS_TABLE_TYPE:
            if not status.test_no:
                record.ip = ip
                continue

        # 3) Otherwise only update if there's a period of downtime.
        # This prevents servers from constantly changing IPs.
        cond_one = cond_two = False
        if not status.last_success and not status.last_uptime:
            if status.test_no >= 2:
                cond_one = True
        if status.last_success:
            elapsed = current_time - status.last_uptime
            if elapsed > (MAX_SERVER_DOWNTIME * 2):
                cond_two = True

        # Only set ip if there's a period of downtime.
        if cond_one or cond_two:
            record.ip = ip