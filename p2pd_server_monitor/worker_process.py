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

async def worker(nic, curl, init_work=None, table_type=None):
    status_ids = []
    try:
        # A single group of work, 1 or more grouped long.
        work = init_work or (await fetch_work_list(curl, table_type))
        if work == INVALID_SERVER_RESPONSE:
            print("Invalid server response, try again.")
            return 0, []
        if not len(work):
            print("No work found")
            return NO_WORK, []

        print("got work = ", work)

        is_success = 0
        status_ids = [w["status_id"] for w in work if "status_id" in w]
        table_type = work[0]["table_type"]

        print()
        proto = "ANY"
        if "proto" in work[0]:
            if work[0]["proto"]:
                proto = TXTS["proto"][work[0]["proto"]]
            
        print("Doing %s work for %s on %s:%s:%d" % (
            TXTS[table_type],
            TXTS[work[0]["type"]] if "type" in work[0] else work[0]["fqn"],
            proto,
            work[0]["ip"],
            int(work[0]["port"] if "port" in work[0] else "53"),
        ))

        if table_type == IMPORTS_TABLE_TYPE:
            is_success = await imports_monitor(curl, work)
            if not is_success:
                print("Offline -- not importing")
            else:
                print("Found -- importing new servers")

        if table_type == SERVICES_TABLE_TYPE:
            is_success = await service_monitor(nic, work)
            if is_success:
                print("Online -- updating uptime", status_ids)
            else:
                print("Offline -- updating uptime", status_ids)
        
        
        if table_type == ALIASES_TABLE_TYPE:
            res_ip = await asyncio.wait_for(
                alias_monitor(curl, work),
                2
            )

            if res_ip:
                params = {"alias_id": int(work[0]["id"]), "ip": res_ip}
                await retry_curl_on_locked(curl, params, "/alias")
                print("Resolved -- updating IPs", status_ids)
            else:
                print("No IP found for DNS -- not updating ", status_ids)
        

        print("Work status updated.")
        return 1, status_ids
    except:
        what_exception()
        log_exception()
        return 0, status_ids

async def process_work(nic, curl, table_type=None, stagger=False):
    while True:
        await sleep_random(100, 4000)

        # Execute work from the dealer server.
        start_time = time.perf_counter()
        is_success, status_ids = await worker(nic, curl, table_type=table_type)

        # Update statuses.
        await update_work_status(curl, status_ids, is_success)

        # If work finished too fast -- add a sleep to avoid DoSing server.     
        exec_elapsed = time.perf_counter() - start_time
        if exec_elapsed <= 0.5:
            ms = int(exec_elapsed * 1000)
            await sleep_random(max(100, 500 - ms), 1000)

        #continue

        # Wait for more work or exit.
        if is_success == NO_WORK:
            if stagger:
                print("Sleeping for a few mins...")
                await sleep_random(30000, 60000)
            else:
                break

async def main(nic=None):
    print("Loading interface...")
    nic = nic or Interface.from_dict(if_info)
    print("Interface loaded: ", nic)

    endpoint = ("127.0.0.1", 8000,)
    route = nic.route(IP4)
    curl = WebCurl(endpoint, route)

    # Keep processing alias work until done.
    # This allows for distributed DNS resolution for imports.
    await process_work(
        nic,
        curl,
        table_type=ALIASES_TABLE_TYPE
    )

    # Give time for all DNS requests to finish.
    await asyncio.sleep(3)

    # Keep processing alias work until done.
    await process_work(nic, curl, stagger=True)

    # Give time for event loop to finish.
    await asyncio.sleep(2)
        
if __name__ == "__main__":
    asyncio.run(main())