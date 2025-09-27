import aiosqlite
from p2pd import *
from .dealer_defs import *
from .dealer_utils import *

async def delete_all_data(db):
    for table in ("settings", "services", "aliases", "status", "imports"):
        sql = "DELETE FROM %s;" % (table)
        await db.execute(sql)

async def init_settings_table(db):
    sql = "INSERT INTO settings (key, value) VALUES (?, ?)"
    params = ("max_server_downtime", MAX_SERVER_DOWNTIME,)
    await db.execute(sql, params)
    await db.commit()

async def insert_services_test_data(db, test_data=SERVICES_TEST_DATA):
    for groups in test_data:
        group_id = await get_new_group_id(db)
        try:
            async with db.execute("BEGIN"):
                # Store alias(es)
                alias_id = None
                try:
                    for fqn in group[0]:
                        alias_id = await fetch_or_insert_alias(db, group[2], fqn)
                        break
                except:
                    log_exception()

                # All items in a group share the same group ID.
                for group in groups:
                    insert_id = await insert_service(
                        db=db,
                        service_type=group[1],
                        af=group[2],
                        proto=group[3],
                        ip=ip_norm(group[4]),
                        port=group[5],
                        user=None,
                        password=None,
                        group_id=group_id,
                        alias_id=alias_id
                    )


                await db.commit()
        except:
            log_exception()

async def insert_imports_test_data(db, test_data=IMPORTS_TEST_DATA):
    for info in test_data:
        fqn = info[0]
        info = info[1:]
        await insert_import(db, *info, fqn=fqn)