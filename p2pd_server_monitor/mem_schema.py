import math
import time
from typing import Any
from .dealer_defs import *
from .work_queue import *
from .schema_defs import *
from p2pd import *

class MemSchema():
    def __init__(self):
        self.setup_db()

    def setup_db(self):
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

    def add_work(self, af: int, table_type: int, group: Any):
        # Save this as a new "group".
        group_id = len(self.groups)
        meta_group = MetaGroup(**{
            "id": group_id,
            "group": group,
            "table_type": table_type,
            "af": af
        })
        self.groups[group_id] = meta_group

        # Add group to work queue LOG(1).
        self.work[table_type][af].add_work(group_id, meta_group, STATUS_INIT)

        # Add group id field.
        for member in group:
            member.group_id = group_id

        return meta_group

    def init_status_row(self, row_id: int, table_type: int):
        # Associated row must exist.
        if row_id not in self.records[table_type]:
            raise KeyError(f"{row_id} not in records {table_type}")
        
        status_id = len(self.statuses)
        status = StatusType(**{
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
        })

        self.statuses[status_id] = status
        return status

    def record_alias(self, af: int, fqn: str, ip=None):
        alias_id = len(self.records[ALIASES_TABLE_TYPE])
        alias = AliasType(**{
            "id": alias_id,
            "af": af,
            "fqn": fqn,
            "ip": ip,
            "group_id": None,
            "status_id": None,
            "table_type": ALIASES_TABLE_TYPE
        })

        # Check unique constraint.
        unique_tup = (af, fqn,)
        if unique_tup in self.unique_alias:
            raise KeyError("Alias already exists" + str(unique_tup))
        else:
            self.unique_alias[unique_tup] = alias

        # Record the new alias.
        self.records[ALIASES_TABLE_TYPE][alias_id] = alias
        self.records_by_aliases[alias_id] = []

        # Create a new status entry for this.
        status = self.init_status_row(alias_id, ALIASES_TABLE_TYPE)
        alias.status_id = status.id

        # Set it up as work.
        self.add_work(af, ALIASES_TABLE_TYPE, [alias])
        return alias

    def fetch_or_insert_alias(self, af: int, fqn: str, ip=None):
        unique_tup = (af, fqn,)
        if unique_tup in self.unique_alias:
            return self.unique_alias[unique_tup]
        else:
            return self.record_alias(af, fqn, ip=ip)

    def insert_record(self, table_type: int, record_type: int, af: int, ip: Any, port: int, user: Any, password: Any, proto=None, fqn=None, alias_id=None, score=0):
        # Some servers like to point to local resources for trickery.
        if ip not in ("0", "", None):
            ensure_ip_is_public(ip)
        else:
            ip = None
            if fqn is None:
                raise ValueError("No way to resolve this IP for insert record.")

        # Load alias row to ensure it exists.
        if alias_id is not None:
            if alias_id not in self.records[ALIASES_TABLE_TYPE]:
                raise KeyError("No alias called id " + str(alias_id))
            else:
                # Disable aliases for STUN change servers.
                if record_type == STUN_CHANGE_TYPE:
                    alias_id = None

        # Get imports id record.
        row_id = len(self.records[table_type])

        # Record imports record.
        record = RecordType(**{
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
            "status_id": None,
            "group_id": None,
            "score": score
        })

        # Check unique constraint.
        unique_tup = (record_type, af, proto, fqn or ip, port,)
        if table_type == SERVICES_TABLE_TYPE:
            unique_dest = self.unique_services
        else:
            unique_dest = self.unique_imports

        if unique_tup in unique_dest:
            raise DuplicateRecordError("Row already exists " + str(unique_tup))
        else:
            unique_dest[unique_tup] = record

        # Save in services table.
        self.records[table_type][row_id] = record

        # Init status row.
        status = self.init_status_row(row_id, table_type)
        record.status_id = status.id

        # Look this up by alias_id.
        if alias_id is not None:
            self.records_by_aliases[alias_id].append(record)

        return record

    def insert_import(self, import_type: int, af: int, ip: Any, port: int, user=None, password=None, fqn=None, score=0):
        # Create alias record.
        if fqn:
            alias = self.fetch_or_insert_alias(af, fqn)
            alias_id = alias.id
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
            alias_id=alias_id,
            fqn=fqn,
            score=score
        )

    def insert_service(self, service_type: int, af: int, proto: int, ip: Any, port: int, user: Any, password: Any, alias_id: Any, score=0):
        return self.insert_record(
            table_type=SERVICES_TABLE_TYPE,
            record_type=service_type,
            af=af,
            ip=ip,
            port=port,
            user=user,
            password=password,
            proto=proto,
            alias_id=alias_id,
            score=score
        )

    def mark_complete(self, is_success: int, status_id: int, t=None):
        t = t or int(time.time())
        status_type = STATUS_AVAILABLE
        if status_id not in self.statuses:
            raise KeyError("could not load status row %s" % (status_id,))
        
        # Delete target row if status is for an imports.
        # We only want imports work to be done once.
        status = self.statuses[status_id]
        table_type = status.table_type
        if table_type == IMPORTS_TABLE_TYPE:
            status_type = STATUS_DISABLED

        # Remove from dealt queue.
        record = self.records[table_type][status.row_id]
        af = record.af
        group_id = record.group_id

        # Try to move work to available -- throw exception if not exist.
        self.work[table_type][af].move_work(group_id, status_type)

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


    def update_table_ip(self, table_type: int, ip: str, alias_id: int, current_time: int):
        for record in self.records_by_aliases[alias_id]:
            # Skip records that don't match the table type.
            if record.table_type != table_type:
                continue

            # SKip disabled records.
            status = self.statuses[record.status_id]
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
