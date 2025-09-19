from p2pd import UDP, TCP, V4, V6

# Placeholder -- fix this.
DB_NAME = "/home/debian/monitor/p2pd-server-monitor/p2pd_server_monitor/monitor.sqlite3"
WORKER_TIMEOUT = 120
MONITOR_FREQUENCY = 10
MAX_SERVER_DOWNTIME = 600

####################################################################################
SERVICE_SCHEMA = ("type", "af", "proto", "ip", "port", "group_id")
STATUS_SCHEMA = ("row_id", "table_type", "status", "last_status", "test_no")
STATUS_SCHEMA += ("failed_tests", "last_success", "last_uptime")
STUN_MAP_TYPE = 1
STUN_CHANGE_TYPE = 2
MQTT_TYPE = 3
TURN_TYPE = 4
NTP_TYPE = 5
PNP_TYPE = 6
SERVICE_TYPES  = (STUN_MAP_TYPE, STUN_CHANGE_TYPE, MQTT_TYPE,)
SERVICE_TYPES += (TURN_TYPE, NTP_TYPE, PNP_TYPE)

STATUS_AVAILABLE = 0
STATUS_DEALT = 1
STATUS_INIT = 2
SERVICES_TABLE_TYPE = 1
ALIASES_TABLE_TYPE = 2
IMPORTS_TABLE_TYPE = 3


####################################################################################
# groups .. group(s) ... fields inc list of fqns associated with it (maybe be blank)
# type * af * proto * group_len = ...
SERVICES_TEST_DATA = [
    [
        [
            ["stun.hot-chilli.net"],
            STUN_CHANGE_TYPE, V4, UDP, "49.12.125.53", 3478
        ],
        [
            ["stun.hot-chilli.net"],
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
]

IMPORTS_TEST_DATA = [
    [
        [
            None,
            STUN_CHANGE_TYPE, V4, UDP, "212.227.67.33", 3478, None, None
        ],
        [
            None,
            STUN_CHANGE_TYPE, V4, UDP, "212.227.67.34", 3479, None, None
        ],
    ],
]