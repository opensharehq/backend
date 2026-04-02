"""Unit tests for ClickHouseDB helper covering error branches."""

from unittest import TestCase, mock

from chdb.clickhousedb import ClickHouseDB


class ClickHouseDBErrorHandlingTests(TestCase):
    """Ensure ClickHouseDB methods log and propagate errors correctly."""

    def tearDown(self):
        """Reset singleton between tests."""
        ClickHouseDB._instance = None

    def test_reset_connection_handles_close_exceptions(self):
        """reset_connection should swallow close errors and clear instance."""

        class BrokenClient:
            def close(self):
                raise RuntimeError("cannot close")

        ClickHouseDB._instance = BrokenClient()
        # Should not raise even though close fails
        ClickHouseDB.reset_connection()
        self.assertIsNone(ClickHouseDB._instance)

    def test_methods_propagate_client_errors(self):
        """query/command/insert/query_df/query_arrow propagate client exceptions."""
        client = mock.Mock()
        client.query.side_effect = RuntimeError("q")
        client.command.side_effect = RuntimeError("c")
        client.insert.side_effect = RuntimeError("i")
        client.query_df.side_effect = RuntimeError("df")
        client.query_arrow.side_effect = RuntimeError("arrow")

        with (
            self.assertLogs("chdb.clickhousedb", level="ERROR") as cm,
            mock.patch.object(ClickHouseDB, "get_instance", return_value=client),
        ):
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

        self.assertEqual(len(cm.output), 5)
        self.assertIn("查询执行失败", cm.output[0])
        self.assertIn("命令执行失败", cm.output[1])
        self.assertIn("数据插入失败", cm.output[2])
        self.assertIn("查询 DataFrame 失败", cm.output[3])
        self.assertIn("查询 Arrow Table 失败", cm.output[4])

    def test_ping_returns_false_on_error(self):
        """Ping should return False when client raises."""
        client = mock.Mock()
        client.ping.side_effect = RuntimeError("ping fail")
        with (
            self.assertLogs("chdb.clickhousedb", level="ERROR") as cm,
            mock.patch.object(ClickHouseDB, "get_instance", return_value=client),
        ):
            self.assertFalse(ClickHouseDB.ping())

        self.assertEqual(len(cm.output), 1)
        self.assertIn("ClickHouse 连接测试失败", cm.output[0])
