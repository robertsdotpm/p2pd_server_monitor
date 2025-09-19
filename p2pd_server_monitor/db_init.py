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

async def insert_services_test_data(db):
    group_id = 0
    for groups in SERVICES_TEST_DATA:
        async with db.execute("BEGIN"):
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
                    alias_id=None
                )
                assert(insert_id is not None)

                # Store alias(es)
                for fqn in group[0]:
                    alias_id = await record_alias(db, group[2], fqn)

            await db.commit()

        group_id += 1

async def insert_imports_test_data(db):
    sql  = "INSERT INTO imports (type, af, ip, port, user, pass, alias_id) "
    sql += "VALUES (?, ?, ?, ?, ?, ?, ?)"
    for info in IMPORTS_TEST_DATA:
        fqn = info[0]
        info = info[1:]
        info[2] = ensure_ip_is_public(info[2])
        try:
            async with db.execute("BEGIN"):
                # Associate alias record with this insert.
                info.append(None)
                try:
                    if fqn:
                        # Update IP field.
                        res = await async_res_domain_af(info[1], fqn)
                        print("resolved fqn for imports")
                        info[2] = res[1]

                        alias_id = await fetch_or_insert_alias(db, info[1], fqn)
                        print("alias id = ", alias_id)
                        info[-1] = alias_id
                except:
                    what_exception()

                # Insert imports record and its status record.
                print("try imports ", info)
                print(sql)

                async with await db.execute(sql, info) as cursor:
                    await init_status_row(
                        db,
                        cursor.lastrowid,
                        IMPORTS_TABLE_TYPE
                    )

                print(cursor.lastrowid)
                await db.commit()
        except:
            what_exception()
            continue
