from p2pd import UDP, TCP, V4, V6

# Placeholder -- fix this.
DB_NAME = "/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/monitor.sqlite3"
WORKER_TIMEOUT = 120
MONITOR_FREQUENCY = 60 * 60
MONITOR_FREQUENCY = 60 # Just temp for testing.
MAX_SERVER_DOWNTIME = 600

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
SERVICES_TABLE_TYPE = 14
ALIASES_TABLE_TYPE = 15
IMPORTS_TABLE_TYPE = 16
NO_WORK = -1


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