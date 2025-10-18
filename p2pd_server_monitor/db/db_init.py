from p2pd import *
from ..defs import *
from ..dealer.dealer_utils import *

async def delete_all_data(sqlite_db):
    for table in ("settings", "services", "aliases", "status", "imports"):
        sql = "DELETE FROM %s;" % (table)
        await sqlite_db.execute(sql)

async def init_settings_table(sqlite_db):
    sql = "INSERT INTO settings (key, value) VALUES (?, ?)"
    params = ("max_server_downtime", MAX_SERVER_DOWNTIME,)
    await sqlite_db.execute(sql, params)
    await sqlite_db.commit()

def insert_imports_test_data(mem_db, test_data):
    for info in test_data:
        fqn = info[0]
        info = info[1:]
        record = mem_db.insert_import(*info, fqn=fqn)

        # Set it up as work.
        mem_db.add_work(record["af"], IMPORTS_TABLE_TYPE, [record])

def insert_services_test_data(mem_db, test_data):
    for groups in test_data:
        records = []

        # All items in a group share the same group ID.
        for group in groups:

            # Store alias(es)
            alias = None
            try:
                for fqn in group[0]:
                    alias = mem_db.fetch_or_insert_alias(group[2], fqn)
                    break
            except:
                log_exception()

            alias_id = alias["id"] if alias else None
            record = mem_db.insert_service(
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

        mem_db.add_work(records[0]["af"], SERVICES_TABLE_TYPE, records)