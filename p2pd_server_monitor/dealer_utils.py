import math
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
    uptime_ratio = (uptime / max_uptime) if max_uptime > 0 else 1.0
    
    quality_score = (
        (1.0 - failed_tests / (test_no + 1e-9)) * 
        (0.5 * uptime_ratio + 0.5) *
        (1.0 - math.exp(-test_no / 50.0))
    )
    
    return quality_score

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
