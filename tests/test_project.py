import asyncio
import unittest
import aiosqlite
from p2pd import *
from p2pd_server_monitor import *

VALID_IMPORTS_TEST_DATA = [
    [None, STUN_MAP_TYPE, V4, "49.12.125.53", 3478, None, None],
    [None, NTP_TYPE, V4, "216.239.35.4", 123, None, None],
    [None, MQTT_TYPE, V4, "44.232.241.40", 1883, None, None],
    [None, TURN_TYPE, V4, "103.253.147.231", 3478, "quickblox", "baccb97ba2d92d71e26eb9886da5f1e0"],
]

class TestProject(unittest.IsolatedAsyncioTestCase):
    @classmethod
    async def init_interface(cls):
        print("before interface")
        cls.nic = await Interface()
        print("set up interface")

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
        print(self.nic)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_settings_table_set(self):
        pass

    async def test_data_should_be_inserted(self):
        await insert_imports_test_data(self.db, VALID_IMPORTS_TEST_DATA)
        sql = "SELECT * FROM imports"
        rows = []
        async with self.db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [[None] + list(row[1:-1]) for row in rows]

        assert(VALID_IMPORTS_TEST_DATA == rows)

    async def test_import_complete_should_delete_status(self):
        await insert_imports_test_data(self.db, VALID_IMPORTS_TEST_DATA)
        work = (await get_work())[0]
        assert(work["table_type"] == IMPORTS_TABLE_TYPE)
        row_id = work["row_id"]
        work = {
            "is_success": 1,
            "status_id": work["status_id"],
            "t": int(time.time())
        }

        await signal_complete_work(str([work]))

        # Attached status should not exist.
        sql = "SELECT * FROM status WHERE id = ?"
        async with self.db.execute(sql, (work["status_id"],)) as cursor:
            rows = await cursor.fetchall()
            assert(not len(rows))

        # Might as well check initial import was deleted.
        sql = "SELECT * FROM imports WHERE id = ?"
        async with self.db.execute(sql, (row_id,)) as cursor:
            rows = await cursor.fetchall()
            assert(not len(rows))

    # TODO: check alias status and service status deleted.

    """
    async def test_import_work_should_be_handed_out_once(self):
        await insert_imports_test_data(self.db, VALID_IMPORTS_TEST_DATA)
        out = await get_work()
        print(out)
    """


    async def test_worker_loop_exception_should_continue(self):
        pass

    async def test_alias_update_should_update_existing_ips(self):
        pass

    async def test_insert_should_create_new_service(self):
        pass

    async def test_insert_list_should_share_group_id(self):
        pass

    async def test_insert_should_increase_group_id(self):
        pass

    async def test_new_alias_should_be_allocatable_as_work(self):
        pass

    async def test_new_import_should_be_allocatable_as_work(self):
        pass

    async def test_new_service_should_be_allocatable_as_work(self):
        pass

    async def test_allocated_work_should_be_marked_allocated(self):
        pass

    async def test_success_work_should_increase_uptime(self):
        pass

    async def test_failed_work_should_reset_uptime(self):
        pass

    async def test_valid_import_should_lead_to_insert(self):
        pass

    async def test_max_uptime_should_be_increase_on_uptime_change(self):
        pass

    async def test_no_should_be_increased_on_complete_change(self):
        pass

    async def test_status_should_be_created_on_insert_api(self):
        pass

    async def test_status_should_be_created_on_new_alias_for_test_data(self):
        pass

    async def test_status_should_be_created_on_new_service_for_test_data(self):
        pass

    async def test_import_continues_on_duplicate_alias(self):
        pass

    async def test_monitor_stun_map_type(self):
        pass

    async def test_monitor_stun_change_type(self):
        pass

    async def test_monitor_mqtt_type(self):
        pass

    async def test_monitor_turn_type(self):
        pass

    async def test_monitor_ntp_type(self):
        pass

    async def test_alias_monitor(self):
        pass

    async def test_imports_monitor(self):
        pass

    async def test_multiple_valid_imports_should_be_reflected_in_servers_list(self):
        pass

