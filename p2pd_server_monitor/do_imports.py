import os
from p2pd import *
from .dealer_utils import *
from .db_init import *

service_lookup = {
    "stun": STUN_MAP_TYPE,
    "mqtt": MQTT_TYPE,
    "turn": TURN_TYPE,
}

file_names = ("/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/imports/stun_v4.csv", "/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/imports/stun_v6.csv", "/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/imports/mqtt_v4.csv", "/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/imports/mqtt_v6.csv", "/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/imports/turn_v4.csv", "/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/imports/turn_v6.csv")

def insert_from_lines(af, import_type, lines, db):
    import_list = []
    for line in lines:
        try:
            line = line.strip()
            parts = line.split(",")
            ip = None if parts[0] in ("0", "") else parts[0]
            port = parts[1]
            user = password = fqn = None
            if len(parts) > 2:
                fqn = parts[2]
            if len(parts) > 3:
                user = parts[3]
            if len(parts) > 4:
                password = parts[4]

            import_record = {
                "import_type": import_type,
                "af": int(af),
                "ip": ip,
                "port": int(port),
                "user": user,
                "password": password,
                "fqn": fqn
            }

            record = db.insert_import(**import_record)
            import_list.append(record)
            db.add_work(af, IMPORTS_TABLE_TYPE, [record])
        except DuplicateRecordError: # ignore really.
            log_exception()
        except:
            what_exception()

    return import_list

def insert_main(db):
    import_list = []
    for file_name in file_names:
        af = IP4 if "v4" in file_name else IP6
        import_type = None
        for service_name in service_lookup:
            if service_name in file_name:
                import_type = service_lookup[service_name]
                break

        if not import_type:
            print("Could not determine import type for file: ", file_name)
            break
            
        file_path = file_name
        if not os.path.exists(file_path):
            print("Could not find file: ", file_path)
            continue


        with open(file_path, "r") as f:
            lines = f.readlines()
            import_list += insert_from_lines(af, import_type, lines, db)

    return import_list