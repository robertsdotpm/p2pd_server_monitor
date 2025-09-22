import asyncio
import aiosqlite
from p2pd import *
from .dealer_defs import *
from .worker_utils import *
from .worker_monitors import *

async def worker(nic, curl, init_work=None):
    try:
        # A single group of work, 1 or more grouped long.
        work = init_work or (await fetch_work_list(curl))
        is_success = status_ids = []
        table_type = work[0]["table_type"]

        print(f"work from table {table_type}")

        if table_type == SERVICES_TABLE_TYPE:
            is_success, status_ids = await service_monitor(nic, work)

        if table_type == IMPORTS_TABLE_TYPE:
            is_success, status_ids = await imports_monitor(curl, work)
        
        if table_type == ALIASES_TABLE_TYPE:
            is_success, status_ids = await alias_monitor(curl, work)


        print("is success = ", is_success)
        print("status ids = ", status_ids)


        await update_work_status(curl, status_ids, is_success)
        #await curl.vars().get("/freshdb")
        return 1
    except:
        log_exception()
        return 0

async def worker_loop(nic=None):
    nic = nic or (await Interface())
    endpoint = ("127.0.0.1", 8000,)
    route = nic.route(IP4)
    curl = WebCurl(endpoint, route)
    while 1:
        print("Fetching work... ")

        is_success = await worker(nic, curl)
        if not is_success:
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(worker_loop1())