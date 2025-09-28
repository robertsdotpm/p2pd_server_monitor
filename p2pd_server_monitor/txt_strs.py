from p2pd import UDP, TCP, V4, V6
from .dealer_defs import *


TXTS = {
    "af": {
        V4: "IPv4",
        V6: "IPv6",
    },
    "proto": {
        TCP: "TCP",
        UDP: "UDP",
    },
    STUN_MAP_TYPE: "STUN Map",
    STUN_CHANGE_TYPE: "STUN Change",
    MQTT_TYPE: "MQTT",
    TURN_TYPE: "TURN",
    NTP_TYPE: "NTP",
    PNP_TYPE: "PNP",
    STATUS_AVAILABLE: "Available",
    STATUS_DEALT: "Dealt",
    STATUS_INIT: "Init",
    STATUS_DISABLED: "Disabled",
    SERVICES_TABLE_TYPE: "services",
    ALIASES_TABLE_TYPE: "aliases",
    IMPORTS_TABLE_TYPE: "imports",  
}

