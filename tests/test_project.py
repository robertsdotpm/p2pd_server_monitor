import asyncio
import unittest
import aiosqlite
import copy
import subprocess
from p2pd import *
from p2pd_server_monitor import *

VALID_IMPORTS_TEST_DATA = [
    [None, STUN_MAP_TYPE, V4, "49.12.125.53", 3478, None, None],
    [None, NTP_TYPE, V4, "216.239.35.4", 123, None, None],
    [None, MQTT_TYPE, V4, "44.232.241.40", 1883, None, None],
    [None, TURN_TYPE, V4, "103.253.147.231", 3478, "quickblox", "baccb97ba2d92d71e26eb9886da5f1e0"],
]

async def run_cmd(*args):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()

class TestProject(unittest.IsolatedAsyncioTestCase):
    @classmethod
    async def init_interface(cls):
        #cls.nic = await Interface()
        cls.nic = None

    @classmethod
    def setUpClass(cls):
        # Run the async setup within the synchronous setUpClass
        asyncio.run(cls.init_interface())

    async def asyncSetUp(self):
        self.db = await aiosqlite.connect(DB_NAME)
        self.db.row_factory = aiosqlite.Row
        await delete_all_data(self.db)
        await init_settings_table(self.db)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_data_should_be_inserted(self):
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        records = db.records[IMPORTS_TABLE_TYPE]
        for i in range(0, len(records)):
            assert(records[i]["ip"] ==  VALID_IMPORTS_TEST_DATA[i][3])


    async def test_import_complete_should_disable_status(self):
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        work = get_work()[0]
        row_id = work["id"]
        comp_status = {
            "is_success": 1,
            "status_id": work["status_id"],
            "t": int(time.time())
        }

        signal_complete_work(str([comp_status]))

        status = db.statuses[work["status_id"]]
        assert(status["status"] == STATUS_DISABLED)
        assert(work["id"] in db.records[IMPORTS_TABLE_TYPE])

    # TODO: check alias status and service status deleted for triggers.

    async def test_import_work_should_be_handed_out_once(self):
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        work = get_work()[0]
        for i in range(0, len(VALID_IMPORTS_TEST_DATA)):
            more_work = get_work()
            if more_work:
                more_work = more_work[0]
                print(work)
                print(more_work)
                assert(work["status_id"] != more_work["status_id"])

    async def test_alias_update_should_update_existing_ips(self):
        fqn = "x.com"
        dns_a = "9.9.9.9"
        fqn_test_data = VALID_IMPORTS_TEST_DATA[:]
        fqn_test_data = [[fqn] + td[1:] for td in fqn_test_data]
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        alias_id = db.fetch_or_insert_alias(int(IP4), fqn)["id"]
        for table_type in TABLE_TYPES:
            for row_id in db.records[table_type]:
                assert(db.records[table_type][row_id]["ip"] != dns_a)

        status_ids = [k for k in db.statuses]

        # Simulate 2 failed checks to ensure downtime > MAX_SERVER_DOWNTIME.
        for i in range(2, 4):
            for status_id in status_ids:
                outcome = {
                    "is_success": 0,
                    "status_id": int(status_id),
                    "t": int(time.time()) + i
                }

                signal_complete_work(str([outcome]))


        update_alias(alias_id, dns_a)
        for table_type in (ALIASES_TABLE_TYPE, SERVICES_TABLE_TYPE,):
            for row_id in db.records[table_type]:
                record = db.records[table_type][row_id]
                assert(record["ip"] == dns_a)
        

    async def test_insert_should_create_new_service(self):
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        work = get_work()[0]
        status_id = work["status_id"]


        service = {
            "service_type": work["type"],
            "af": int(work["af"]),
            "proto": int(UDP),
            "ip": work["ip"],
            "port": work["port"],
            "user": work["user"],
            "password": work["pass"],
            "alias_id": work["alias_id"]
        }

        assert(not len(db.records[SERVICES_TABLE_TYPE]))
        
        insert_services(str([[service]]), status_id)
        assert(len(db.records[SERVICES_TABLE_TYPE]))

    async def test_import_list_group_id_assumptions(self):
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        work = get_work()[0]
        status_id = work["status_id"]

        primary = {
            "service_type": STUN_CHANGE_TYPE,
            "af": int(IP4),
            "proto": int(UDP),
            "ip": "8.8.8.8",
            "port": 8000,
            "user": None,
            "password": None,
            "alias_id": None
        }

        secondary = copy.deepcopy(primary)
        secondary["ip"] = "8.8.4.4"

        another = copy.deepcopy(secondary)
        another["ip"] = "4.4.4.4"

        imports_list = [
            [primary, secondary],
            [another]
        ]

        insert_services(str(imports_list), status_id)

        rows = list(db.records[SERVICES_TABLE_TYPE].values())
        assert(rows[0]["group_id"] == rows[1]["group_id"])
        assert(rows[0]["group_id"] != rows[2]["group_id"])

    async def test_new_alias_should_be_allocatable_as_work(self):
        alias = db.fetch_or_insert_alias(int(IP4), "x.com")
        work = get_work()
        assert(len(work))

    async def test_work_reallocated_after_worker_timeout(self):
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        for i in range(0, len(VALID_IMPORTS_TEST_DATA)):
            work = get_work()

        work = get_work()
        assert(not len(work))

        # Simulate fetch work after a long time.
        work = get_work(current_time=int(time.time()) + (WORKER_TIMEOUT * 2))
        assert(len(work))        

    async def test_work_not_allocated_before_second_threshold(self):
        test_data = SERVICES_TEST_DATA[:]
        for group in test_data:
            db.insert_services_test_data([group])
            work = get_work(monitor_frequency=10)
            assert(len(work))

            work_list = work[:]
            for serv in work_list:
                signal = {
                    "is_success": 1,
                    "status_id": serv["status_id"],
                    "t": int(time.time())
                }

                signal_complete_work(str([signal]))

            work = get_work()
            assert(not len(work))


            for serv in work_list:
                signal = {
                    "is_success": 1,
                    "status_id": serv["status_id"],
                    "t": int(time.time())
                }

                signal_complete_work(str([signal]))

            work = get_work()
            assert(not len(work))

            t = int(time.time()) + (MONITOR_FREQUENCY * 2)

            work = get_work(current_time=t)
            assert(len(work))

    async def test_allocated_work_should_be_marked_allocated(self):
        db.insert_imports_test_data(VALID_IMPORTS_TEST_DATA)
        work = get_work()
        found = False
        for af in (IP4, IP6,):
            qs = db.work[IMPORTS_TABLE_TYPE][af].queues
            for allocated in qs[STATUS_DEALT]:
                if allocated[1]["group"] == work:
                    found = True

        assert(found)

    async def test_success_work_should_increase_uptime(self):
        await insert_imports_test_data(self.db)
        work = (await get_work())[0]
        service = {
            "service_type": work["type"],
            "af": work["af"],
            "proto": int(UDP),
            "ip": "8.8.8.8",
            "port": work["port"],
            "user": work["user"],
            "password": work["pass"],
            "alias_id": work["alias_id"]
        }


        await insert_services(str([[service]]), work["status_id"])

        # Indicate complete for import work.
        work = {
            "is_success": 1,
            "status_id": work["status_id"],
            "t": int(time.time()) + 2
        }

        await signal_complete_work(str([work]))

        # Indicate complete for service work.
        work = (await get_work())[0]
        work = {
            "is_success": 1,
            "status_id": work["status_id"],
            "t": int(time.time()) + 2
        }
        await signal_complete_work(str([work]))
        work["t"] += 2
        await signal_complete_work(str([work]))

        # Check if uptime went up.
        sql = "SELECT * FROM status WHERE table_type = ?"
        async with self.db.execute(sql, (SERVICES_TABLE_TYPE,)) as cursor:
            row = dict((await cursor.fetchall())[0])
            print(row)
            assert(row["uptime"])
            assert(row["uptime"] == row["max_uptime"])
            assert(row["test_no"] == 2)


    async def test_failed_work_should_reset_uptime(self):
        await insert_services_test_data(self.db)
        work = (await get_work())[0]

        # First -- set uptime and max_uptime to a positive value.
        indicate_success = {
            "is_success": 1,
            "status_id": work["status_id"],
            "t": int(time.time()) + 2
        }

        await signal_complete_work(str([indicate_success]))
        indicate_success["t"] += 2
        await signal_complete_work(str([indicate_success]))

        # Then -- indicate a failed test.
        indicate_failure = {
            "is_success": 0,
            "status_id": work["status_id"],
            "t": int(time.time()) + 4
        }

        await signal_complete_work(str([indicate_failure]))


        sql = "SELECT * FROM status WHERE id = ?"
        async with self.db.execute(sql, (work["status_id"],)) as cursor:
            row = dict((await cursor.fetchall())[0])
            assert(not row["uptime"])
            assert(row["max_uptime"])
            assert(row["test_no"] == 3)

    async def test_monitor_stun_map_type(self):
        work = [{
            "af": IP4,
            "ip": "74.125.250.129", # Google
            "port": 19302,
            "proto": UDP,
            "status_id": None,
        }]


        is_success = await monitor_stun_map_type(self.nic, work)
        assert(is_success)

    async def test_monitor_stun_change_type(self):
        servers = [
            {"ip": "49.12.125.53", "port": 3478},
            {"ip": "49.12.125.53", "port": 3479},
            {"ip": "49.12.125.24", "port": 3478},
            {"ip": "49.12.125.24", "port": 3479},
        ]

        servers[0]["af"] = IP4
        servers[0]["proto"] = UDP
        for server in servers:
            server["status_id"] = None

        is_success = await monitor_stun_change_type(self.nic, servers)
        assert(is_success)

    async def test_monitor_mqtt_type(self):
        servers = [{
            "af": IP4,
            "proto": UDP,
            "ip": "44.232.241.40",
            "port": 1883,
            "status_id": None
        }]

        is_success = await monitor_mqtt_type(self.nic, servers)
        assert(is_success)


    async def test_monitor_turn_type(self):
        servers = [{
            "af": IP4,
            "proto": UDP,
            "ip": "103.253.147.231",
            "port": 3478,
            "status_id": None,
            "user": "quickblox",
            "pass": "baccb97ba2d92d71e26eb9886da5f1e0"
        }]

        is_success = await monitor_turn_type(self.nic, servers)
        assert(is_success)

    async def test_monitor_ntp_type(self):
        servers = [{
            "af": IP4,
            "proto": UDP,
            "ip": "216.239.35.4",
            "port": 123,
            "status_id": None
        }]

        is_success = await monitor_ntp_type(self.nic, servers)
        assert(is_success)

    async def test_alias_monitor(self):
        route = self.nic.route(IP4)
        curl = WebCurl(("23.220.75.245", 80,), route)
        alias = [{
            "fqn": "www.example.com",
            "af": IP4,
            "row_id": 0,
            "status_id": 0,
        }]

        is_success = await alias_monitor(curl, alias)
        assert(is_success)

    async def test_imports_monitor(self):
        route = self.nic.route(IP4)
        curl = WebCurl(("23.220.75.245", 80,), route)
        servers = []
        for info in VALID_IMPORTS_TEST_DATA:
            server = {
                "type": info[1],
                "af": info[2],
                "ip": info[3],
                "port": info[4],
                "user": info[5],
                "pass": info[6],
                "alias_id": 0,
                "status_id": 0,
            }

            await imports_monitor(curl, [server])


    async def test_worker_loop_exception_should_continue(self):
        is_success, _ = await worker(self.nic, None)
        assert(not is_success)

    async def test_status_should_be_created_on_new_alias(self):
        await fetch_or_insert_alias(self.db, IP4, "example.com")
        sql = "SELECT * FROM status"
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            assert(rows)

    async def test_ipv6_works_at_all(self):
        test_data = [
            [
                None,
                MQTT_TYPE, V6, "2607:5300:60:80b0::1", 1883, None, None
            ],
        ]

        route = self.nic.route(IP4)
        curl = WebCurl(("8.8.8.8", 80,), route)
        servers = []
        for info in test_data:
            server = {
                "type": info[1],
                "af": info[2],
                "ip": info[3],
                "port": info[4],
                "user": info[5],
                "pass": info[6],
                "alias_id": 0,
                "status_id": 0,
            }

            await imports_monitor(curl, [server])

    async def test_insert_imports_with_invalid_data_should_fail(self):
        await insert_imports_test_data(self.db, VALID_IMPORTS_TEST_DATA)
        work = dict((await get_work())[0])
        status_id = work["status_id"]
        service = {
            "service_type": work["type"],
            "af": work["af"],
            "proto": int(UDP),
            "ip": "8.8.8.8",
            "port": work["port"],
            "user": work["user"],
            "password": work["pass"],
            "alias_id": work["alias_id"]
        }

        try:
            bad_ip = copy.deepcopy(service)
            bad_ip["ip"] = "835sfasd"
            await insert_services(str([[bad_ip]]), status_id)
            assert(0)
        except:
            pass

        try:
            bad_port = copy.deepcopy(service)
            bad_port["port"] = 5365452634
            await insert_services(str([[bad_port]]), status_id)
            assert(0)
        except:
            pass

        try:
            bad_proto = copy.deepcopy(service)
            bad_proto["proto"] = 5365452634
            await insert_services(str([[bad_proto]]), status_id)
            assert(0)
        except:
            pass

        try:
            bad_service_type = copy.deepcopy(service)
            bad_service_type["service_type"] = 4234
            await insert_services(str([[bad_service_type]]), status_id)
            assert(0)
        except:
            pass

        try:
            bad_af = copy.deepcopy(service)
            bad_af["af"] = 1337
            await insert_services(str([[bad_af]]), status_id)
            assert(0)
        except:
            pass

    async def test_service_deletion_should_remove_related_status(self):
        test_data = SERVICES_TEST_DATA[:]
        for group in test_data:
            await insert_services_test_data(self.db, test_data=[group])

        work = await get_work()
        sql = "DELETE FROM services WHERE id = ?"
        async with self.db.execute(sql, (work[0]["row_id"],)) as cursor:
            await self.db.commit()

        sql = "SELECT * FROM status WHERE id = ?"
        async with self.db.execute(sql, (work[0]["status_id"],)) as cursor:               
            rows = await cursor.fetchall()
            assert(not len(rows))   

    async def test_alias_created_for_import(self):
        fqn = "stun.gmx.de"
        import_id = await insert_import(
            db=self.db,
            import_type=STUN_MAP_TYPE,
            af=IP4,
            ip="212.227.67.33",
            port=3478,
            fqn=fqn,
        )

        assert(import_id)

        sql = "SELECT * FROM aliases"
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [dict(row) for row in rows]

        sql = "SELECT * FROM imports"
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [dict(row) for row in rows]
            assert(rows[0]["alias_id"])

        sql = "SELECT * FROM status"
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [dict(row) for row in rows]

        # ^ should have two status rows.
        # Got to check its allocated as work.
        work_list = []
        work = await get_work()
        work_list.append(work[0])

        work = await get_work()
        work_list.append(work[0])

        # check worker process can handle alias work.
        alias_work = None
        import_work = None
        for work in work_list:
            if work["table_type"] == ALIASES_TABLE_TYPE:
                alias_work = work
            else:
                import_work = work

        # Not exactly the same as the process worker doing it with a web call.
        service = {
            "service_type": import_work["type"],
            "af": import_work["af"],
            "proto": int(UDP),
            "ip": import_work["ip"],
            "port": import_work["port"],
            "user": import_work["user"],
            "password": import_work["pass"],
            "alias_id": alias_work["id"]
        }

        await insert_services(str([[service]]), import_work["status_id"])

        # check imports monitor can handle alias work.
        route = self.nic.route(IP4)
        curl = WebCurl(("8.8.8.8", 80,), route)
        is_success, status_ids = await worker(self.nic, curl, init_work=[alias_work])

        sql = "SELECT * FROM status"
        status_ids = []
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [dict(row) for row in rows]
            for row in rows:
                status_ids.append(row["id"])

        # Simulate 2 failed checks to ensure downtime > MAX_SERVER_DOWNTIME.
        for i in range(2, 4):
            for status_id in status_ids:
                outcome = {
                    "is_success": 0,
                    "status_id": int(status_id),
                    "t": int(time.time()) + i
                }

                await signal_complete_work(str([outcome]))

        # Simulate an API update from a worker.
        sim_ip = "9.1.2.3"
        future_time = int(time.time()) + (MAX_SERVER_DOWNTIME * 3)
        await update_alias(alias_work["id"], sim_ip, current_time=future_time)

        # Imports are only done once so they should not have changed.
        sql = "SELECT * FROM imports"
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [dict(row) for row in rows]
            assert(rows[0]["ip"] != sim_ip)

        # Check services changes.
        sql = "SELECT * FROM services"
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [dict(row) for row in rows]
            assert(rows[0]["ip"] == sim_ip)

    async def test_monitor_turn_type_with_wrong_credentials(self):
        # Pass wrong user/pass to monitor_turn_type and assert failure
        pass

    async def test_alias_monitor_with_unresolvable_fqn_returns_status_ids(self):
        return
        
        # Pass an unresolvable FQN and assert failure
        route = self.nic.route(IP4)
        curl = WebCurl(("example.com", 80), route)
        ret = await alias_monitor(curl, alias)

    async def test_server_list_has_quality_score_set(self):
        pass

    # All work should end up being allocated, processed, then made available.
    # Then test that can be done multiple times.
    async def test_systemctl_cleans_out_work_queue_multiple_times(self):
        # Run do imports.
        print("Importing all saved servers.")
        result = subprocess.run(
            "python3 -m p2pd_server_monitor.do_imports".split(" "),
            check=True,
            text=True,
            capture_output=True,
            cwd="/home/debian/monitor/p2pd_server_monitor/p2pd_server_monitor"
        )
        print("Importing done.")

        """
        # Start systemctrl ...
        print("Starting monitoring system")
        result = subprocess.run(
            "sudo systemctl restart p2pd_monitor".split(" "),
            check=True,
            text=True,
            capture_output=True
        )
        """

        # Wait for alias work to be done.
        print("Waiting for alias work to be done.")
        rows = 1
        sql = "SELECT * FROM status WHERE table_type=? AND status != ?"
        params = (ALIASES_TABLE_TYPE, STATUS_AVAILABLE,)
        while rows:
            async with self.db.execute(sql, params) as cursor:
                await asyncio.sleep(1)
                rows = await cursor.fetchall()
                rows = [dict(row) for row in rows]
                print(len(rows))

        print("All aliases processed.")

        """
        # Stop systemctrl.
        print("stopping monitoring system")
        result = subprocess.run(
            "sudo systemctl stop p2pd_monitor".split(" "),
            check=True,
            text=True,
            capture_output=True
        )
        """