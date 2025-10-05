"""

group_p = n
statuses = {id: status_record}
groups_by_p = {group_id: ref} --> [status ...]
work_groups = [table_type][groups ...]  --> [status ...]
                FIFO stack
                deque
                popleft O(1) and append O(1)

main_records = [table_type]{id: record}
    record = {
    }

for record in init:
    init pop --> dealt append --> alloc

for record in available
    if 


for record in dealt:
        if elapsed < worker_timeout
            all subequent ones are more recent
            break
        else:
            adealt remove -> dealt append --> alloc
"""

import math
import time
from typing_extensions import TypedDict
from typing import Any, List
from pydantic import BaseModel
from .dealer_defs import *
from .work_queue import *
from p2pd import *

class AliasType(BaseModel):
    id: int
    af: int
    fqn: str
    ip: str | None
    group_id: int
    status_id: int
    table_type: int

class RecordType(BaseModel):
    id: int
    table_type: int
    type: int
    af: int
    proto: int | None
    ip: str | None
    port: int
    user: str | None
    password: str | None
    alias_id: int | None
    status_id: int
    group_id: int

class MemSchema():
    def __init__(self):
        self.delete_all()

    def delete_all(self):
        self.statuses = {} # id: status
        self.groups = {} # group_id: [status ...]
        self.work = {} # [table_type] -> queue -> [status ...]
        for table_type in TABLE_TYPES:
            self.work[table_type] = {}
            for af in [IP4, IP6]:
                self.work[table_type][int(af)] = WorkQueue()

        self.records = {} # [table_type][id] => record
        for table_type in TABLE_TYPES:
            self.records[table_type] = {}
            

        self.records_by_aliases = {}
        self.records_by_ip = {}
        self.unique_imports = {}
        self.unique_services = {}
        self.unique_alias = {}

    def add_work(self, af, table_type, group):
        # Save this as a new "group".
        group_id = len(self.groups)
        meta_group = {
            "id": group_id,
            "group": group,
            "table_type": table_type,
            "af": af
        }
        self.groups[group_id] = meta_group

        # Add group to work queue LOG(1).
        self.work[table_type][af].add_work(group_id, meta_group, STATUS_INIT)

        # Add group id field.
        for member in group:
            member["group_id"] = group_id

        return meta_group

    def init_status_row(self, row_id, table_type):
        status_id = len(self.statuses)
        status = {
            "id": status_id,
            "row_id": row_id,
            "table_type": table_type,
            "status": STATUS_INIT,
            "last_status": int(time.time()),
            "test_no": 0,
            "failed_tests": 0,
            "last_success": 0,
            "last_uptime": 0,
            "uptime": 0,
            "max_uptime": 0
        }

        self.statuses[status_id] = status
        return status

    def record_alias(self, af, fqn, ip=None):
        alias_id = len(self.records[ALIASES_TABLE_TYPE])
        alias = {
            "id": alias_id,
            "af": af,
            "fqn": fqn,
            "ip": ip,
            "group_id": None,
            "status_id": None,
            "table_type": ALIASES_TABLE_TYPE
        }

        # Check unique constraint.
        unique_tup = frozenset([af, fqn])
        if unique_tup in self.unique_alias:
            raise Exception("Alias already exists" + str(unique_tup))
        else:
            self.unique_alias[unique_tup] = alias

        # Create a new status entry for this.
        status = self.init_status_row(alias_id, ALIASES_TABLE_TYPE)
        alias["status_id"] = status["id"]
        
        # Record the new alias.
        self.records[ALIASES_TABLE_TYPE][alias_id] = alias
        self.records_by_aliases[alias_id] = []

        # Set it up as work.
        self.add_work(af, ALIASES_TABLE_TYPE, [alias])
        return alias

    def fetch_or_insert_alias(self, af, fqn, ip=None):
        unique_tup = frozenset([af, fqn])
        if unique_tup in self.unique_alias:
            return self.unique_alias[unique_tup]
        else:
            return self.record_alias(af, fqn, ip=ip)

    def insert_record(self, table_type, record_type, af, ip, port, user, password, proto=None, fqn=None, alias_id=None):
        # Some servers like to point to local resources for trickery.
        if ip not in ("0", ""):
            ensure_ip_is_public(ip)
        else:
            ip = None

        # Sanity tests.
        """
        if af not in VALID_AFS:
            raise Exception("Invalid AF for insert record.")
        if not valid_port(port):
            raise Exception("Invalid port.")
        if proto not in (None, TCP, UDP):
            raise Exception("Invalid proto.")
        """

        # Load alias row to ensure it exists.
        if alias_id is not None:
            if alias_id not in self.records[ALIASES_TABLE_TYPE]:
                raise Exception("No alias called id " + str(alias_id))
            else:
                # Disable aliases for STUN change servers.
                if record_type == STUN_CHANGE_TYPE:
                    alias_id = None

        # Get imports id record.
        row_id = len(self.records[table_type])

        # Init status row.
        status = self.init_status_row(row_id, table_type)

        # Record imports record.
        record = {
            "id": row_id,
            "table_type": table_type,
            "type": record_type,
            "af": af,
            "proto": proto,
            "ip": ip,
            "port": port,
            "user": user,
            "password": password,
            "alias_id": alias_id,
            "status_id": status["id"],
            "group_id": None
        }

        # Check unique constraint.
        unique_tup = frozenset([record_type, af, proto, ip, port])
        if table_type == SERVICES_TABLE_TYPE:
            unique_dest = self.unique_services
        else:
            unique_dest = self.unique_imports

        if unique_tup in unique_dest:
            raise Exception("Row already exists " + str(unique_tup))
        else:
            unique_dest[unique_tup] = record

        # Save in services table.
        self.records[table_type][row_id] = record

        # Look this up by alias_id.
        if alias_id is not None:
            self.records_by_aliases[alias_id].append(record)

        return record

    def insert_import(self, import_type, af, ip, port, user=None, password=None, fqn=None):
        # Create alias record.
        af = int(af)
        if fqn:
            alias = self.fetch_or_insert_alias(af, fqn)
            alias_id = alias["id"]
        else:
            alias_id = None

        
        return self.insert_record(
            table_type=IMPORTS_TABLE_TYPE,
            record_type=import_type,
            af=af,
            ip=ip,
            port=port,
            user=user,
            password=password,
            alias_id=alias_id
        )

    def insert_service(self, service_type, af, proto, ip, port, user, password, alias_id):
        af = int(af)
        proto = int(proto)
        return self.insert_record(
            table_type=SERVICES_TABLE_TYPE,
            record_type=service_type,
            af=af,
            ip=ip,
            port=port,
            user=user,
            password=password,
            proto=proto,
            alias_id=alias_id
        )

    def mark_complete(self, is_success, status_id, t=None):
        t = t or int(time.time())

        status_type = STATUS_AVAILABLE
        if status_id not in self.statuses:
            raise Exception("could not load status row %s" % (status_id,))
        
        # Delete target row if status is for an imports.
        # We only want imports work to be done once.
        status = self.statuses[status_id]
        table_type = status["table_type"]
        if table_type == IMPORTS_TABLE_TYPE:
            status_type = STATUS_DISABLED

        if is_success:
            if not status["last_uptime"]:
                change = 0
            else:
                change = t - status["last_uptime"]

            status["uptime"] += change
            if status["uptime"] > status["max_uptime"]:
                status["max_uptime"] = status["uptime"]

            status["last_uptime"] = t
            status["last_success"] = t

        if not is_success:
            status["failed_tests"] += 1
            status["uptime"] = 0
        
        status["status"] = status_type
        status["test_no"] += 1
        status["last_status"] = t

        # Remove from dealt queue.
        record = self.records[table_type][status["row_id"]]
        af = record["af"]
        group_id = record["group_id"]
        self.work[table_type][af].move_work(group_id, status_type)

    def update_table_ip(self, table_type, ip, alias_id, current_time):
        for record in self.records_by_aliases[alias_id]:
            if record["table_type"] != table_type:
                continue

            status = self.statuses[record["status_id"]]
            if status["status"] == STATUS_DISABLED:
                continue

            print("update table ip = ", record)

            cond_one = not status["last_success"] and \
                not status["last_uptime"] and \
                status["test_no"] >= 2

            cond_two = status["last_success"] and \
                ((current_time - status["last_uptime"]) > MAX_SERVER_DOWNTIME * 2)

            print("cond one = ", cond_one)
            print("cond two = ", cond_two)

            if not (cond_one or cond_two):
                continue

            record["ip"] = ip

    def insert_imports_test_data(self, test_data=IMPORTS_TEST_DATA):
        for info in test_data:
            fqn = info[0]
            info = info[1:]
            record = self.insert_import(*info, fqn=fqn)

            # Set it up as work.
            self.add_work(record["af"], IMPORTS_TABLE_TYPE, [record])

    def insert_services_test_data(self, test_data=SERVICES_TEST_DATA):
        for groups in test_data:
            records = []

            # All items in a group share the same group ID.
            for group in groups:

                # Store alias(es)
                alias = None
                try:
                    for fqn in group[0]:
                        alias = self.fetch_or_insert_alias(group[2], fqn)
                        break
                except:
                    log_exception()

                alias_id = alias["id"] if alias else None
                record = self.insert_service(
                    service_type=group[1],
                    af=group[2],
                    proto=group[3],
                    ip=ip_norm(group[4]),
                    port=group[5],
                    user=None,
                    password=None,
                    alias_id=alias_id
                )

                records.append(record)

            self.add_work(records[0]["af"], SERVICES_TABLE_TYPE, records)

def compute_service_score(status, max_uptime_override=None):
    """
    Compute the quality score for a single service status.
    
    status: dict with keys:
        - failed_tests
        - test_no
        - uptime
        - max_uptime
        - last_status
    
    max_uptime_override: optional, to replace status['max_uptime'] for calculation
    """
    failed_tests = float(status.get("failed_tests", 0))
    test_no = float(status.get("test_no", 0))
    uptime = float(status.get("uptime", 0))
    max_uptime = float(status.get("max_uptime", 0)) if max_uptime_override is None else float(max_uptime_override)
    
    # Avoid division by zero
    uptime_ratio = (uptime / max_uptime) if max_uptime > 0 else 1.0
    
    quality_score = (
        (1.0 - failed_tests / (test_no + 1e-9)) * 
        (0.5 * uptime_ratio + 0.5) *
        (1.0 - math.exp(-test_no / 50.0))
    )
    
    return quality_score
