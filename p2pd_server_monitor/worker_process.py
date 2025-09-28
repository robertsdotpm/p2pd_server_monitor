import asyncio
from p2pd import *
from .dealer_defs import *
from .worker_utils import *
from .worker_monitors import *
from .txt_strs import *

async def worker(nic, curl, init_work=None):
    try:
        # A single group of work, 1 or more grouped long.
        work = init_work or (await fetch_work_list(curl))
        if not len(work):
            print("No work found")
            return 0

        is_success = status_ids = []
        table_type = work[0]["table_type"]

        print()
        print("Doing %s work for %s on %s:%s:%d" % (
            TXTS[table_type],
            TXTS[work[0]["type"]],
            TXTS["proto"][work[0]["proto"]] if "proto" in work[0] else "ANY",
            work[0]["ip"],
            work[0]["port"],
        ))

        if table_type == SERVICES_TABLE_TYPE:
            is_success, status_ids = await service_monitor(nic, work)
            if not status_ids:
                print("Error -- unable to update status.")
            else:
                if is_success:
                    print("Online -- updating uptime", status_ids)
                else:
                    print("Offline -- updating uptime", status_ids)

        if table_type == IMPORTS_TABLE_TYPE:
            is_success, status_ids = await imports_monitor(curl, work)
            if not status_ids:
                print("Offline -- not importing")
            else:
                print("Found -- importing new servers", status_ids)
        
        if table_type == ALIASES_TABLE_TYPE:
            is_success, status_ids = await alias_monitor(curl, work)
            if not status_ids:
                print("Error -- update IP from DNS name.")
            else:
                if is_success:
                    print("Resolved -- updating IPs", status_ids)
                else:
                    print("No IP found for DNS -- not updating ", status_ids)

        await update_work_status(curl, status_ids, is_success)
        #await curl.vars().get("/freshdb")
        return 1
    except:
        log_exception()
        return 0

async def worker_loop(nic=None):
    print("Loading interface...")
    nic = nic or (await Interface())
    print("Interface loaded: ", nic)

    endpoint = ("127.0.0.1", 8000,)
    route = nic.route(IP4)
    curl = WebCurl(endpoint, route)
    while 1:
        try:
            is_success = await asyncio.wait_for(
                worker(nic, curl), timeout=6
            )
        except asyncio.TimeoutError:
            is_success = 0

        if not is_success:
            await asyncio.sleep(1)
        
if __name__ == "__main__":
    asyncio.run(worker_loop())