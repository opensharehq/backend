"""ClickHouse 数据库集成测试."""

import threading
from unittest import mock
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


class ClickHouseDBErrorHandlingTests(TestCase):
    """Ensure error branches log but still propagate exceptions."""

    def tearDown(self):
        """Reset singleton cache between tests."""
        ClickHouseDB._instance = None

    def test_reset_connection_handles_close_exceptions(self):
        """reset_connection should swallow close errors and clear instance."""

        class BrokenClient:
            def close(self):
                msg = "cannot close"
                raise RuntimeError(msg)

        ClickHouseDB._instance = BrokenClient()
        ClickHouseDB.reset_connection()
        self.assertIsNone(ClickHouseDB._instance)

    def test_methods_propagate_client_errors(self):
        """query/command/insert/query_df/query_arrow should re-raise client errors."""
        client = mock.Mock()
        client.query.side_effect = RuntimeError("q")
        client.command.side_effect = RuntimeError("c")
        client.insert.side_effect = RuntimeError("i")
        client.query_df.side_effect = RuntimeError("df")
        client.query_arrow.side_effect = RuntimeError("arrow")

        with mock.patch.object(ClickHouseDB, "get_instance", return_value=client):
            with self.assertRaises(RuntimeError):
                ClickHouseDB.query("select 1")
            with self.assertRaises(RuntimeError):
                ClickHouseDB.command("cmd")
            with self.assertRaises(RuntimeError):
                ClickHouseDB.insert("tbl", [])
            with self.assertRaises(RuntimeError):
                ClickHouseDB.query_df("select 1")
            with self.assertRaises(RuntimeError):
                ClickHouseDB.query_arrow("select 1")

    def test_ping_returns_false_on_error(self):
        """Ping returns False when client raises an exception."""
        client = mock.Mock()
        client.ping.side_effect = RuntimeError("ping fail")
        with mock.patch.object(ClickHouseDB, "get_instance", return_value=client):
            self.assertFalse(ClickHouseDB.ping())


class SearchTagsTests(TestCase):
    """search_tags 函数测试."""

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_basic(self, mock_query):
        """测试基本搜索功能."""
        from chdb import services

        # Mock ClickHouse 查询结果
        mock_result = MagicMock()
        mock_result.result_rows = [
            ["github-microsoft-vscode", "repo", "github", "microsoft/vscode", 1234.56],
            ["gitee-microsoft-vscode", "repo", "gitee", "microsoft/vscode", 567.89],
        ]
        mock_query.return_value = mock_result

        # 执行搜索
        tags = services.search_tags("vscode")

        # 验证结果
        self.assertEqual(len(tags), 2)

        # 验证第一个标签
        self.assertEqual(tags[0]["id"], "github-microsoft-vscode")
        self.assertEqual(tags[0]["type"], "repo")
        self.assertEqual(tags[0]["platform"], "github")
        self.assertEqual(tags[0]["name"], "microsoft/vscode")
        self.assertEqual(tags[0]["openrank"], 1234.56)
        self.assertEqual(tags[0]["name_display"], "microsoft/vscode (Github)")
        self.assertEqual(tags[0]["slug"], "github-microsoft-vscode")

        # 验证第二个标签
        self.assertEqual(tags[1]["id"], "gitee-microsoft-vscode")
        self.assertEqual(tags[1]["platform"], "gitee")
        self.assertEqual(tags[1]["name_display"], "microsoft/vscode (Gitee)")

        # 验证查询调用
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        self.assertIn("name_info", call_args[0][0])
        self.assertIn("ILIKE", call_args[0][0])
        self.assertIn("LIMIT", call_args[0][0])
        self.assertIn("BY type, platform", call_args[0][0])
        self.assertEqual(call_args[1]["parameters"]["keyword"], "%vscode%")
        self.assertEqual(call_args[1]["parameters"]["limit"], 5)

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_empty_keyword(self, mock_query):
        """测试空关键词处理."""
        from chdb import services

        # 空字符串
        tags = services.search_tags("")
        self.assertEqual(tags, [])
        mock_query.assert_not_called()

        # 仅空格
        tags = services.search_tags("   ")
        self.assertEqual(tags, [])
        mock_query.assert_not_called()

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_no_results(self, mock_query):
        """测试无结果场景."""
        from chdb import services

        # Mock 空结果
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        tags = services.search_tags("nonexistent-project-xyz")

        self.assertEqual(tags, [])
        mock_query.assert_called_once()

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_custom_limit(self, mock_query):
        """测试自定义 limit 参数."""
        from chdb import services

        # Mock 结果
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        # 使用自定义 limit
        services.search_tags("test", limit=10)

        # 验证 limit 参数
        call_args = mock_query.call_args
        self.assertEqual(call_args[1]["parameters"]["limit"], 10)

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_query_exception(self, mock_query):
        """测试查询异常处理."""
        from chdb import services

        # Mock 查询抛出异常
        mock_query.side_effect = Exception("Database connection error")

        # 执行搜索，应该返回空列表而不是抛出异常
        tags = services.search_tags("vscode")

        self.assertEqual(tags, [])
        mock_query.assert_called_once()

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_keyword_trimmed(self, mock_query):
        """测试关键词前后空格被正确去除."""
        from chdb import services

        # Mock 结果
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        # 搜索带空格的关键词
        services.search_tags("  vscode  ")

        # 验证去除空格后的关键词
        call_args = mock_query.call_args
        self.assertEqual(call_args[1]["parameters"]["keyword"], "%vscode%")


class GetLabelUsersTests(TestCase):
    """get_label_users 函数测试."""

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_basic(self, mock_query):
        """测试基本用户信息查询."""
        from chdb import services

        # Mock ClickHouse 查询结果
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "github-microsoft-vscode",
                ["github", "gitee"],  # platforms.name
                [  # platforms.users (嵌套数组)
                    [123, 456],  # github 用户
                    [789],  # gitee 用户
                ],
            ],
        ]
        mock_query.return_value = mock_result

        # 执行查询
        label_info = services.get_label_users(["github-microsoft-vscode"])

        # 验证结果
        self.assertEqual(len(label_info), 1)
        self.assertIn("github-microsoft-vscode", label_info)

        info = label_info["github-microsoft-vscode"]
        self.assertEqual(info["platforms"], ["github", "gitee"])
        self.assertEqual(info["users"]["github"], [123, 456])
        self.assertEqual(info["users"]["gitee"], [789])

        # 验证查询调用
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        self.assertIn("opensource.labels", call_args[0][0])
        self.assertIn("platforms.name", call_args[0][0])
        self.assertIn("platforms.users", call_args[0][0])
        self.assertEqual(
            call_args[1]["parameters"]["label_ids"], ["github-microsoft-vscode"]
        )

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_empty_list(self, mock_query):
        """测试空标签列表处理."""
        from chdb import services

        label_info = services.get_label_users([])

        self.assertEqual(label_info, {})
        mock_query.assert_not_called()

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_normalizes_ids(self, mock_query):
        """测试标签 ID 规范化处理."""
        from chdb import services

        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        label_info = services.get_label_users([16060815, " 37247796 ", None, ""])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        self.assertEqual(
            call_args[1]["parameters"]["label_ids"], ["16060815", "37247796"]
        )

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_no_results(self, mock_query):
        """测试无结果场景."""
        from chdb import services

        # Mock 空结果
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        label_info = services.get_label_users(["nonexistent-label"])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_multiple_labels(self, mock_query):
        """测试查询多个标签."""
        from chdb import services

        # Mock 多个标签的结果
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "github-microsoft-vscode",
                ["github"],
                [[123, 456]],
            ],
            [
                "github-facebook-react",
                ["github", "gitlab"],
                [[789], [321, 654]],
            ],
        ]
        mock_query.return_value = mock_result

        label_info = services.get_label_users(
            ["github-microsoft-vscode", "github-facebook-react"]
        )

        # 验证结果
        self.assertEqual(len(label_info), 2)
        self.assertIn("github-microsoft-vscode", label_info)
        self.assertIn("github-facebook-react", label_info)

        # 验证第一个标签
        self.assertEqual(label_info["github-microsoft-vscode"]["platforms"], ["github"])
        self.assertEqual(
            label_info["github-microsoft-vscode"]["users"]["github"], [123, 456]
        )

        # 验证第二个标签
        self.assertEqual(
            label_info["github-facebook-react"]["platforms"], ["github", "gitlab"]
        )
        self.assertEqual(label_info["github-facebook-react"]["users"]["github"], [789])
        self.assertEqual(
            label_info["github-facebook-react"]["users"]["gitlab"], [321, 654]
        )

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_query_exception(self, mock_query):
        """测试查询异常处理."""
        from chdb import services

        # Mock 查询抛出异常
        mock_query.side_effect = Exception("Database connection error")

        # 执行查询，应该返回空字典而不是抛出异常
        label_info = services.get_label_users(["github-microsoft-vscode"])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()

    @mock.patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_mismatched_array_lengths(self, mock_query):
        """测试平台名称和用户数组长度不匹配的情况."""
        from chdb import services

        # Mock 结果：platforms.name 有 2 个元素，但 platforms.users 只有 1 个
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "test-label",
                ["github", "gitlab"],  # 2 个平台
                [[123]],  # 只有 1 个用户数组
            ],
        ]
        mock_query.return_value = mock_result

        label_info = services.get_label_users(["test-label"])

        # 验证结果：只映射第一个平台
        self.assertEqual(len(label_info), 1)
        info = label_info["test-label"]
        self.assertEqual(info["platforms"], ["github", "gitlab"])
        self.assertEqual(info["users"]["github"], [123])
        self.assertNotIn("gitlab", info["users"])  # gitlab 没有用户数据
