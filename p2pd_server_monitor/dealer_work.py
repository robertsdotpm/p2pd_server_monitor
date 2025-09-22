import aiosqlite
from p2pd import *
from .dealer_defs import *
from .dealer_utils import *

async def fetch_group_records(db, status_entry, need_af):
    """Fetch records for a given status entry."""
    table_type = status_entry["table_type"]
    row_id = status_entry["row_id"]

    if table_type == SERVICES_TABLE_TYPE:
        group_id = None
        async with db.execute(
            "SELECT group_id FROM services WHERE id=? LIMIT 1", (row_id,)
        ) as cursor:
            ref = await cursor.fetchone()
            if ref is None:
                return []

            group_id = dict(ref)["group_id"]

        table_name = "services"
        where_clause = "group_id=? AND af LIKE ?"
        params = (group_id, need_af,)
    else:
        table_name = (
            "aliases" if table_type == ALIASES_TABLE_TYPE else "imports"
        )
        where_clause = f"{table_name}.id=? AND af LIKE ?"
        params = (row_id, need_af,)

    sql = f"""
    SELECT {table_name}.*, s.id AS status_id, s.*
    FROM {table_name}
    LEFT JOIN status AS s ON s.row_id = {table_name}.id
    WHERE {where_clause};
    """

    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

def check_allocatable(group_records, current_time, monitor_frequency):
    """Return allocatable records if all in group are ready, else []."""
    allocatable_records = []
    for record in group_records:
        if record["status"] == STATUS_INIT:
            allocatable_records.append(record)
            continue

        elapsed = current_time - record["last_status"]
        if elapsed < 0:
            continue

        print("elapsed = ", elapsed)
        print("monitor freq = ", monitor_frequency)
        print("status = ", record["status"])

        if record["status"] == STATUS_DEALT:
            if elapsed >= WORKER_TIMEOUT:
                record["status"] = STATUS_AVAILABLE

        if elapsed < monitor_frequency:
            record["status"] = STATUS_DEALT

        if record["status"] == STATUS_AVAILABLE:
            allocatable_records.append(record)

    # Everything in group must be ready
    if len(group_records) != len(allocatable_records):
        return []

    return allocatable_records

async def claim_group(db, group_records, alloc_time):
    """Atomically claim all status rows for a group if all are available or timed out."""
    status_ids = [record["status_id"] for record in group_records]
    t = alloc_time or int(time.time())

    # First, check eligibility
    sql_check = f"""
    SELECT status, last_status FROM status
    WHERE id IN ({','.join(['?']*len(status_ids))})
    """
    async with db.execute(sql_check, status_ids) as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            # If any row is STATUS_DEALT and not timed out, cannot claim
            if row["status"] == STATUS_DEALT and t < row["last_status"] + WORKER_TIMEOUT:
                return False

    # All rows are available or timed out, proceed to claim
    async with db.execute("BEGIN"):
        sql_update = f"""
        UPDATE status
        SET status=?, last_status=?
        WHERE id IN ({','.join(['?']*len(status_ids))})
        """
        params = [STATUS_DEALT, t] + status_ids
        result = await db.execute(sql_update, params)
        await db.commit()

        # Only proceed if all rows were updated (claimed)
        return result.rowcount == len(status_ids)

async def mark_complete(db, is_success, status_id, t):
    # Delete the associated imports row and status record.
    try:
        # Load status row to check it exists.
        row = await load_status_row(db, status_id)
        if row is None:
            raise Exception("could not load status row.")

        # Delete target row if status is for an imports.
        # We only want imports work to be done once.
        if row["table_type"] == IMPORTS_TABLE_TYPE:
            sql = "DELETE FROM imports WHERE id = ?"
            await db.execute(sql, (row["row_id"],))
            return []
    except:
        # Can't load status so return.
        log_exception()
        return []

    # Update fields if a server test was successful.
    if is_success:
        print("in is success")
        sql = """
        UPDATE status
        SET
            -- Start counting if this is the first success.
            -- Otherwise increment it based on the starting timestamp.
            uptime = uptime + CASE 
                WHEN last_uptime = 0 
                THEN 0 
                ELSE (? - last_uptime) 
            END,

            -- Don't update last_uptime if it's already set.
            last_uptime = CASE 
                WHEN last_uptime = 0 
                THEN ? 
                ELSE last_uptime 
            END,


            test_no = test_no + 1,
            status = ?,
            last_status = ?,
            last_success = ?
        WHERE id = ?;
        """
        params = (
            t,  # uptime increment
            t,  # last_uptime reset if zero
            STATUS_AVAILABLE,
            t,  # last_status
            t,  # last_success
            status_id,
        )
        await db.execute(sql, params)

    # Update server fields assuming it failed.
    if not is_success:
        sql = """
        UPDATE status
        SET
            status = ?,
            last_status = ?,
            failed_tests = failed_tests + 1,
            test_no = test_no + 1
        WHERE id = ?;
        """
        await db.execute(sql, (STATUS_AVAILABLE, t, status_id))

    return []