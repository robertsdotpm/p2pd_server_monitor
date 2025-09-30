import asyncio
import aiosqlite
from fastapi.responses import JSONResponse
from typing import Union, Any
from p2pd import *
from .dealer_defs import *

class PrettyJSONResponse(JSONResponse):
    def render(self, content: any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,        # pretty-print here
        ).encode("utf-8")

def ensure_ip_is_public(ip):
    ip = ip_norm(ip)
    af = IP4 if "." in ip else IP6
    ipr = IPRange(ip, af_to_cidr(af))
    if ipr.is_private:
        raise Exception("IP must be public.")

    return ip

async def init_status_row(db, row_id, table_type):
    # Parameterized insert
    sql  = "INSERT INTO status (%s) VALUES " % (", ".join(STATUS_SCHEMA)) 
    sql += "(?, ?, ?, ?, ?, ?, ?, ?)"
    t    = int(time.time())

    async with await db.execute(
        sql,
        (row_id, table_type, STATUS_INIT, t, 0, 0, 0, 0,)
    ) as cursor:
        return cursor.lastrowid
    
async def load_status_row(db, status_id):
    sql = "SELECT * FROM status WHERE id=?"
    async with db.execute(sql, (status_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None

async def record_alias(db, af, fqn, ip=None):
    sql = "INSERT into aliases (af, fqn, ip) VALUES (?, ?, ?)"
    alias_id = None
    async with await db.execute(sql, (af, fqn, ip,)) as cursor:
        alias_id = cursor.lastrowid

    await init_status_row(
        db,
        alias_id,
        ALIASES_TABLE_TYPE
    )

    return alias_id

async def load_alias_row(db, alias_id):
    sql = "SELECT * FROM aliases WHERE id=?"
    async with db.execute(sql, (alias_id,)) as cursor:
        rows = await cursor.fetchone()
        if rows:
            return rows

    return None

async def fetch_or_insert_alias(db, af, fqn, ip=None):
    sql = "SELECT * FROM aliases WHERE af=? AND fqn=?"
    async with db.execute(sql, (af, fqn,)) as cursor:
        rows = await cursor.fetchone()
        if rows:
            return dict(rows)["id"]

    return await record_alias(db, af, fqn, ip)

async def get_new_group_id(db):
    # Insert a dummy row and get its id atomically
    async with db.execute("INSERT INTO groups DEFAULT VALUES") as cursor:
        await db.commit()
        return cursor.lastrowid

async def insert_import(db, import_type, af, ip, port, user=None, password=None, fqn=None):
    if ip not in ("", "0"):
        ip = ensure_ip_is_public(ip)
    sql  = "INSERT INTO imports (type, af, ip, port, user, pass, alias_id) "
    sql += "VALUES (?, ?, ?, ?, ?, ?, ?)"
    info = [import_type, af, ip, port, user, password, None]
    import_id = None

    # Associate alias record with this insert.
    if fqn:
        try:
            alias_id = await fetch_or_insert_alias(db, af, fqn)
            info[-1] = alias_id
        except:
            log("Fqn error for %s" % (fqn,))
            log_exception()

    async with db.execute(sql, info) as cursor:
        import_id = cursor.lastrowid
        await init_status_row(
            db,
            cursor.lastrowid,
            IMPORTS_TABLE_TYPE
        )

        await db.commit()
        return import_id


async def insert_service(
    db,
    service_type,
    af,
    proto,
    ip,
    port,
    user,
    password,
    group_id,
    alias_id
):
    # Some servers like to point to local resources for trickery.
    ip = ensure_ip_is_public(ip)

    # Load alias row to ensure it exists.
    if alias_id:
        alias_row = await load_alias_row(db, alias_id)
        if not alias_row:
            raise Exception("Alias ID does not exist.")

        # Disable aliases for STUN change servers.
        if service_type == STUN_CHANGE_TYPE:
            alias_id = None

    # SQL statement for insert into services.
    sql  = """
    INSERT INTO services 
        (type, af, proto, ip, port, user, pass, group_id, alias_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    # Execute the query and make a status row for it.
    params  = (service_type, af, proto, ip, port, user,)
    params += (password, group_id, alias_id,)
    insert_id = status_id = None
    async with db.execute(sql, params) as cursor:
        insert_id = cursor.lastrowid
        status_id = await init_status_row(
            db,
            insert_id,
            SERVICES_TABLE_TYPE
        )

    return [status_id, insert_id]

async def update_table_ip(db, table_name, ip, alias_id, current_time):
    sql = f"""
    UPDATE {table_name}
    SET ip = ?
    WHERE alias_id = ?
      AND EXISTS (
          SELECT 1
          FROM status
          WHERE status.row_id = {table_name}.id
            AND status.status != {STATUS_DISABLED}
            AND (
                (
                    status.last_success = 0
                    AND status.last_uptime = 0
                    AND status.test_no >= 2
                )
                OR
                (
                    status.last_success != 0
                    AND (? - status.last_uptime) > ?
                )
            )
      );
    """
    params = (ip, alias_id, current_time, MAX_SERVER_DOWNTIME * 2,)
    await db.execute(sql, params)