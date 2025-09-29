import asyncio
import random
from p2pd import *
from .dealer_defs import *
from .worker_utils import *
from .worker_monitors import *
from .txt_strs import *

"""
While I update the list of servers, loading WAN addresses is going to be broken.
So I'll manually set this for both speed and reliability.
"""
if_info = {'id': 'eno1',
 'is_default': {2: True, 10: True},
 'mac': '00-1e-67-fa-5d-42',
 'name': 'eno1',
 'nat': {'delta': {'type': 1, 'value': 0},
         'delta_info': 'not applicable',
         'nat_info': 'open internet',
         'type': 1},
 'netiface_index': 1,
 'nic_no': 0,
 'rp': {2: [{'af': 2,
             'ext_ips': [{'af': 2, 'cidr': 32, 'ip': '158.69.27.176'}],
             'link_local_ips': [],
             'nic_ips': [{'af': 2, 'cidr': 32, 'ip': '158.69.27.176'}]}],
        10: [{'af': 10,
             'ext_ips': [{'af': 10, 'cidr': 128, 'ip': '2607:5300:60:80b0::1'}],
             'link_local_ips': [],
             'nic_ips': [{'af': 10, 'cidr': 128, 'ip': '2607:5300:60:80b0::1'}]}]
        }
}

async def worker(nic, curl, init_work=None):
    try:
        # A single group of work, 1 or more grouped long.
        work = init_work or (await fetch_work_list(curl))
        if not len(work):
            print("No work found")
            return NO_WORK

        is_success = status_ids = []
        table_type = work[0]["table_type"]

        print()
        print("Doing %s work for %s on %s:%s:%d" % (
            TXTS[table_type],
            TXTS[work[0]["type"]] if "type" in work[0] else work[0]["fqn"],
            TXTS["proto"][work[0]["proto"]] if "proto" in work[0] else "ANY",
            work[0]["ip"],
            int(work[0]["port"] if "port" in work[0] else "53"),
        ))

        if table_type == IMPORTS_TABLE_TYPE:
            is_success, status_ids = await imports_monitor(curl, work)
            if not is_success:
                print("Offline -- not importing")
            else:
                print("Found -- importing new servers")

        if table_type == SERVICES_TABLE_TYPE:
            is_success, status_ids = await service_monitor(nic, work)
            if not status_ids:
                print("Error -- unable to update status.")
            else:
                if is_success:
                    print("Online -- updating uptime", status_ids)
                else:
                    print("Offline -- updating uptime", status_ids)
        
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
        what_exception()
        log_exception()
        return 0

async def worker_loop(nic=None):
    print("Loading interface...")
    nic = nic or Interface.from_dict(if_info)
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

        if is_success == NO_WORK:
            # Random stagger period before retry.
            # This avoids every worker hitting the server at once.
            # It also distributes work evenly over time.
            n = random.randrange(1, MONITOR_FREQUENCY)
            print("Sleeping until next try in secs: ", n)
            await asyncio.sleep(n)

        # Avoid DoS in event of error.
        await asyncio.sleep(0.1)
        
if __name__ == "__main__":
    asyncio.run(worker_loop())