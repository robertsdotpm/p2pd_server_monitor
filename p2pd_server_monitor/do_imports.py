import os
import asyncio
import aiosqlite
from p2pd import *
from .dealer_utils import *
from .db_init import *
from .dealer_work import *

service_lookup = {
    "stun": STUN_MAP_TYPE,
}

file_names = ("/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor/imports/stun_v4.csv",)


def insert_main(db):
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
        print(file_path)
        if not os.path.exists(file_path):
            print("Could not find file: ", file_path)
            continue


        with open(file_path, "r") as f:
            lines = f.readlines()
            for line in lines:
                try:
                    line = line.strip()
                    parts = line.split(",")
                    ip = parts[0]
                    port = parts[1]
                    fqn = None
                    if len(parts) > 2:
                        fqn = parts[2]
                        print("Trying fqn = ", fqn)

                    record = db.insert_import(
                        import_type=import_type,
                        af=af,
                        ip=ip,
                        port=int(port),
                        user=None,
                        password=None,
                        fqn=fqn
                    )

                    print("import id = ", record["id"])
                except:
                    what_exception()
