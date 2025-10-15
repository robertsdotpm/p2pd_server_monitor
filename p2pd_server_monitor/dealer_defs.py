from p2pd import UDP, TCP, V4, V6
from typing import Any, List, Optional
from pydantic import BaseModel

# Placeholder -- fix this.
DB_NAME = "/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/monitor.sqlite3"
WORKER_TIMEOUT = 120
MONITOR_FREQUENCY = 60 * 60
MONITOR_FREQUENCY = 60 * 60 # Just temp for testing.
MAX_SERVER_DOWNTIME = 600
IMPORT_TEST_NO = 3 # Try to import items 3 times then stop.

####################################################################################
SERVICE_SCHEMA = ("type", "af", "proto", "ip", "port", "group_id")
STATUS_SCHEMA = ("row_id", "table_type", "status", "last_status", "test_no")
STATUS_SCHEMA += ("failed_tests", "last_success", "last_uptime")
STUN_MAP_TYPE = 3
STUN_CHANGE_TYPE = 4
MQTT_TYPE = 5
TURN_TYPE = 6
NTP_TYPE = 7
PNP_TYPE = 8
SERVICE_TYPES  = (STUN_MAP_TYPE, STUN_CHANGE_TYPE, MQTT_TYPE,)
SERVICE_TYPES += (TURN_TYPE, NTP_TYPE, PNP_TYPE)

STATUS_AVAILABLE = 9
STATUS_DEALT = 11
STATUS_INIT = 12
STATUS_DISABLED = 13
STATUS_TYPES = (STATUS_INIT, STATUS_AVAILABLE, STATUS_DEALT, STATUS_DISABLED,)
SERVICES_TABLE_TYPE = 14
ALIASES_TABLE_TYPE = 15
IMPORTS_TABLE_TYPE = 16
GROUPS_TABLE_TYPE = 17
STATUS_TABLE_TYPE = 18
NO_WORK = -1
INVALID_SERVER_RESPONSE = -2
TABLE_TYPES = (SERVICES_TABLE_TYPE, ALIASES_TABLE_TYPE, IMPORTS_TABLE_TYPE,)


####################################################################################
# groups .. group(s) ... fields inc list of fqns associated with it (maybe be blank)
# type * af * proto * group_len = ...
SERVICES_TEST_DATA = [
    [
        [
            [],
            STUN_CHANGE_TYPE, V4, UDP, "49.12.125.53", 3478
        ],
        [
            [],
            STUN_CHANGE_TYPE, V4, UDP, "49.12.125.53", 3479
        ],
        [
            [],
            STUN_CHANGE_TYPE, V4, UDP, "49.12.125.24", 3478
        ],
        [
            [],
            STUN_CHANGE_TYPE, V4, UDP, "49.12.125.24", 3479
        ],
    ],
    
    [
        [[], NTP_TYPE, V4, UDP, "216.239.35.4", 123],
    ]
    
]

IMPORTS_TEST_DATA = [
    [None, STUN_MAP_TYPE, V4, "49.12.125.53", 3478, None, None],
]

class DuplicateRecordError(KeyError):
    """Raised when a duplicate key is inserted."""
    pass

class ServiceData(BaseModel):
    service_type: int
    af: int
    proto: int
    ip: str
    port: int
    user: str | None
    password: str | None
    alias_id: int | None
    score: int

class InsertServicesReq(BaseModel):
    imports_list: List[List[ServiceData]]
    status_id: int

class WorkResultData(BaseModel):
    status_id: int
    is_success: int
    t: int

class WorkDoneReq(BaseModel):
    statuses: List[WorkResultData]

class AliasUpdateReq(BaseModel):
    alias_id: int
    ip: str
    current_time: int | None = None

class GetWorkReq(BaseModel):
    stack_type: int | None
    table_type: int | None
    current_time: int | None
    monitor_frequency: int | None

    