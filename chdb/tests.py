"""ClickHouse 数据库集成测试."""

import threading
from unittest.mock import MagicMock, Mock

from django.test import TestCase

from chdb import clickhousedb
from chdb.clickhousedb import ClickHouseDB, command, insert, query


class ClickHouseMonkeyPatchedTestCase(TestCase):
    """给 ClickHouse 连接打桩, 避免测试时建立真实连接."""

    def setUp(self):
        """为每个用例替换 clickhouse 连接工厂."""
        super().setUp()
        ClickHouseDB.reset_connection()

        self.client_mock = Mock(name="clickhouse_client")
        self.original_get_client = clickhousedb.clickhouse_connect.get_client
        self.get_client_mock = Mock(return_value=self.client_mock)

        # monkeypatch clickhouse_connect.get_client -> mock
        clickhousedb.clickhouse_connect.get_client = self.get_client_mock

    def tearDown(self):
        """还原 monkeypatch 并清理单例."""
        # 还原 monkeypatch，清理单例
        clickhousedb.clickhouse_connect.get_client = self.original_get_client
        ClickHouseDB.reset_connection()
        super().tearDown()


class ClickHouseDBTests(ClickHouseMonkeyPatchedTestCase):
    """ClickHouse 数据库封装类测试."""

    def test_get_instance_creates_singleton(self):
        """测试 get_instance 创建单例."""
        instance1 = ClickHouseDB.get_instance()
        instance2 = ClickHouseDB.get_instance()

        # 验证返回相同实例
        self.assertIs(instance1, instance2)
        # 验证只调用一次 get_client
        self.get_client_mock.assert_called_once()

    def test_get_instance_thread_safety(self):
        """测试 get_instance 线程安全性."""
        instances = []
        errors = []

        def create_instance():
            try:
                instance = ClickHouseDB.get_instance()
                instances.append(instance)
            except Exception as e:
                errors.append(e)

        # 创建多个线程并发获取实例
        threads = [threading.Thread(target=create_instance) for _ in range(10)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # 验证没有错误发生
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")

        # 验证所有实例都相同
        self.assertEqual(len(instances), 10)
        self.assertTrue(all(inst is instances[0] for inst in instances))

        # 验证只调用一次 get_client
        self.get_client_mock.assert_called_once()

    def test_reset_connection(self):
        """测试重置连接."""
        # 创建实例
        instance1 = ClickHouseDB.get_instance()
        self.assertIsNotNone(instance1)

        # 重置连接
        ClickHouseDB.reset_connection()

        # 验证 close 被调用
        self.client_mock.close.assert_called_once()

        # 重新获取应该创建新实例
        self.get_client_mock.reset_mock()
        mock_client2 = Mock(name="clickhouse_client_second")
        self.client_mock = mock_client2
        self.get_client_mock.return_value = mock_client2

        instance2 = ClickHouseDB.get_instance()

        # 验证重新调用了 get_client
        self.get_client_mock.assert_called_once()
        # 验证获取了新实例
        self.assertEqual(instance2, mock_client2)

    def test_reset_connection_thread_safety(self):
        """测试 reset_connection 线程安全性."""
        # 先创建实例
        ClickHouseDB.get_instance()

        errors = []

        def reset_instance():
            try:
                ClickHouseDB.reset_connection()
            except Exception as e:
                errors.append(e)

        # 多线程并发重置
        threads = [threading.Thread(target=reset_instance) for _ in range(5)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # 验证没有错误
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")

    def test_query(self):
        """测试查询方法."""
        mock_result = Mock(name="query_result")
        self.client_mock.query.return_value = mock_result

        result = ClickHouseDB.query("SELECT 1")

        self.client_mock.query.assert_called_once_with(
            "SELECT 1", parameters=None, settings=None
        )
        self.assertEqual(result, mock_result)

    def test_query_with_parameters(self):
        """测试带参数的查询."""
        mock_result = Mock(name="query_result_with_params")
        self.client_mock.query.return_value = mock_result

        params = {"id": 1}
        result = ClickHouseDB.query("SELECT * FROM test WHERE id = {id:UInt32}", params)

        self.client_mock.query.assert_called_once_with(
            "SELECT * FROM test WHERE id = {id:UInt32}",
            parameters=params,
            settings=None,
        )
        self.assertEqual(result, mock_result)

    def test_command(self):
        """测试命令方法."""
        mock_result = Mock(name="command_result")
        self.client_mock.command.return_value = mock_result

        result = ClickHouseDB.command("CREATE TABLE test (id UInt32)")

        self.client_mock.command.assert_called_once_with(
            "CREATE TABLE test (id UInt32)", parameters=None, settings=None
        )
        self.assertEqual(result, mock_result)

    def test_insert(self):
        """测试插入方法."""
        data = [[1, "test"], [2, "test2"]]
        columns = ["id", "name"]

        ClickHouseDB.insert("test_table", data, columns)

        self.client_mock.insert.assert_called_once_with(
            "test_table", data, column_names=columns, settings=None
        )

    def test_query_df(self):
        """测试 DataFrame 查询."""
        mock_df = MagicMock()
        self.client_mock.query_df.return_value = mock_df

        result = ClickHouseDB.query_df("SELECT 1")

        self.client_mock.query_df.assert_called_once_with(
            "SELECT 1", parameters=None, settings=None
        )
        self.assertEqual(result, mock_df)

    def test_query_arrow(self):
        """测试 Arrow 查询."""
        mock_table = Mock(name="arrow_table")
        self.client_mock.query_arrow.return_value = mock_table

        result = ClickHouseDB.query_arrow("SELECT 1")

        self.client_mock.query_arrow.assert_called_once_with(
            "SELECT 1", parameters=None, settings=None
        )
        self.assertEqual(result, mock_table)

    def test_ping_success(self):
        """测试 ping 成功."""
        self.client_mock.ping.return_value = True

        # 先创建实例
        ClickHouseDB.get_instance()

        result = ClickHouseDB.ping()

        self.assertTrue(result)
        self.client_mock.ping.assert_called_once()

    def test_ping_connection_fails(self):
        """测试 ping 连接失败."""
        # 模拟连接创建失败
        self.get_client_mock.side_effect = Exception("Connection failed")

        result = ClickHouseDB.ping()
        self.assertFalse(result)
        self.get_client_mock.assert_called_once()

    def test_ping_exception(self):
        """测试 ping 异常."""
        self.client_mock.ping.side_effect = Exception("Connection lost")

        # 先创建实例
        ClickHouseDB.get_instance()

        result = ClickHouseDB.ping()

        self.assertFalse(result)


class ConvenienceFunctionsTests(ClickHouseMonkeyPatchedTestCase):
    """便捷函数测试."""

    def test_query_function(self):
        """测试 query 便捷函数."""
        mock_result = Mock(name="query_result")
        self.client_mock.query.return_value = mock_result

        result = query("SELECT 1")

        self.assertEqual(result, mock_result)

    def test_command_function(self):
        """测试 command 便捷函数."""
        mock_result = Mock(name="command_result")
        self.client_mock.command.return_value = mock_result

        result = command("SHOW TABLES")

        self.assertEqual(result, mock_result)

    def test_insert_function(self):
        """测试 insert 便捷函数."""
        data = [[1, "test"]]
        insert("test_table", data, ["id", "name"])

        self.client_mock.insert.assert_called_once()
