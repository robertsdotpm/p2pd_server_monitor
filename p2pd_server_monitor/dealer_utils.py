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

    print(sql)
    
    async with await db.execute(
        sql,
        (row_id, table_type, STATUS_INIT, t, 0, 0, 0, t,)
    ) as cursor:
        return cursor.lastrowid
    
async def load_status_row(db, status_id):
    sql = "SELECT * FROM status WHERE id=?"
    async with db.execute(sql, (status_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None

async def record_alias(db, af, fqn):
    sql = "INSERT into aliases (af, fqn) VALUES (?, ?)"
    alias_id = None
    async with await db.execute(sql, (af, fqn,)) as cursor:
        alias_id = cursor.lastrowid

    await init_status_row(
        db,
        alias_id,
        ALIASES_TABLE_TYPE
    )

    return alias_id

async def fetch_or_insert_alias(db, af, fqn):
    sql = "SELECT * FROM aliases WHERE af=? AND fqn=?"
    async with db.execute(sql, (af, fqn,)) as cursor:
        rows = await cursor.fetchone()
        if rows:
            return rows[0]["id"]

    return await record_alias(db, af, fqn)

async def get_max_group_id(db):
    sql = "SELECT IFNULL(MAX(group_id), 0) FROM services"
    async with db.execute(sql) as cursor:
        return (await cursor.fetchone())[0]

    return 0

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

