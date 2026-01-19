"""Tests for ClickHouseDB client wrapper."""

import threading
from unittest.mock import MagicMock, Mock

from django.test import TestCase

from chdb import clickhousedb
from chdb.clickhousedb import ClickHouseDB, command, insert, query


class ClickHouseMonkeyPatchedTestCase(TestCase):
    """Mock ClickHouse connection to avoid real connections in tests."""

    def setUp(self):
        """Patch clickhouse_connect.get_client for each test."""
        super().setUp()
        ClickHouseDB.reset_connection()

        self.client_mock = Mock(name="clickhouse_client")
        self.original_get_client = clickhousedb.clickhouse_connect.get_client
        self.get_client_mock = Mock(return_value=self.client_mock)

        clickhousedb.clickhouse_connect.get_client = self.get_client_mock

    def tearDown(self):
        """Restore monkeypatch and clear singleton."""
        clickhousedb.clickhouse_connect.get_client = self.original_get_client
        ClickHouseDB.reset_connection()
        super().tearDown()


class ClickHouseDBTests(ClickHouseMonkeyPatchedTestCase):
    """Tests for ClickHouseDB wrapper class."""

    def test_get_instance_creates_singleton(self):
        """get_instance should return singleton and reuse it."""
        instance1 = ClickHouseDB.get_instance()
        instance2 = ClickHouseDB.get_instance()

        self.assertIs(instance1, instance2)
        self.get_client_mock.assert_called_once()

    def test_get_instance_thread_safety(self):
        """get_instance should be thread-safe."""
        instances = []
        errors = []

        def create_instance():
            try:
                instance = ClickHouseDB.get_instance()
                instances.append(instance)
            except Exception as exc:  # pragma: no cover - diagnostic safety
                errors.append(exc)

        threads = [threading.Thread(target=create_instance) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(instances), 10)
        self.assertTrue(all(inst is instances[0] for inst in instances))
        self.get_client_mock.assert_called_once()

    def test_reset_connection(self):
        """reset_connection should close and clear instance."""
        instance1 = ClickHouseDB.get_instance()
        self.assertIsNotNone(instance1)

        ClickHouseDB.reset_connection()

        self.client_mock.close.assert_called_once()

        self.get_client_mock.reset_mock()
        mock_client2 = Mock(name="clickhouse_client_second")
        self.client_mock = mock_client2
        self.get_client_mock.return_value = mock_client2

        instance2 = ClickHouseDB.get_instance()

        self.get_client_mock.assert_called_once()
        self.assertEqual(instance2, mock_client2)

    def test_reset_connection_thread_safety(self):
        """reset_connection should be thread-safe."""
        ClickHouseDB.get_instance()

        errors = []

        def reset_instance():
            try:
                ClickHouseDB.reset_connection()
            except Exception as exc:  # pragma: no cover - diagnostic safety
                errors.append(exc)

        threads = [threading.Thread(target=reset_instance) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")

    def test_query(self):
        """query should delegate to client.query."""
        mock_result = Mock(name="query_result")
        self.client_mock.query.return_value = mock_result

        result = ClickHouseDB.query("SELECT 1")

        self.client_mock.query.assert_called_once_with(
            "SELECT 1", parameters=None, settings=None
        )
        self.assertEqual(result, mock_result)

    def test_query_with_parameters(self):
        """query should pass parameters."""
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
        """command should delegate to client.command."""
        mock_result = Mock(name="command_result")
        self.client_mock.command.return_value = mock_result

        result = ClickHouseDB.command("CREATE TABLE test (id UInt32)")

        self.client_mock.command.assert_called_once_with(
            "CREATE TABLE test (id UInt32)", parameters=None, settings=None
        )
        self.assertEqual(result, mock_result)

    def test_insert(self):
        """insert should delegate to client.insert."""
        data = [[1, "test"], [2, "test2"]]
        columns = ["id", "name"]

        ClickHouseDB.insert("test_table", data, columns)

        self.client_mock.insert.assert_called_once_with(
            "test_table", data, column_names=columns, settings=None
        )

    def test_query_df(self):
        """query_df should delegate to client.query_df."""
        mock_df = MagicMock()
        self.client_mock.query_df.return_value = mock_df

        result = ClickHouseDB.query_df("SELECT 1")

        self.client_mock.query_df.assert_called_once_with(
            "SELECT 1", parameters=None, settings=None
        )
        self.assertEqual(result, mock_df)

    def test_query_arrow(self):
        """query_arrow should delegate to client.query_arrow."""
        mock_table = Mock(name="arrow_table")
        self.client_mock.query_arrow.return_value = mock_table

        result = ClickHouseDB.query_arrow("SELECT 1")

        self.client_mock.query_arrow.assert_called_once_with(
            "SELECT 1", parameters=None, settings=None
        )
        self.assertEqual(result, mock_table)

    def test_ping_success(self):
        """ping should return True when client responds."""
        self.client_mock.ping.return_value = True

        ClickHouseDB.get_instance()

        result = ClickHouseDB.ping()

        self.assertTrue(result)
        self.client_mock.ping.assert_called_once()

    def test_ping_connection_fails(self):
        """ping should return False when connection fails."""
        self.get_client_mock.side_effect = Exception("Connection failed")

        result = ClickHouseDB.ping()
        self.assertFalse(result)
        self.get_client_mock.assert_called_once()

    def test_ping_exception(self):
        """ping should return False when client ping fails."""
        self.client_mock.ping.side_effect = Exception("Connection lost")

        ClickHouseDB.get_instance()

        result = ClickHouseDB.ping()

        self.assertFalse(result)


class ConvenienceFunctionsTests(ClickHouseMonkeyPatchedTestCase):
    """Tests for module-level convenience functions."""

    def test_query_function(self):
        """query convenience function should delegate to ClickHouseDB.query."""
        mock_result = Mock(name="query_result")
        self.client_mock.query.return_value = mock_result

        result = query("SELECT 1")

        self.assertEqual(result, mock_result)

    def test_command_function(self):
        """command convenience function should delegate to ClickHouseDB.command."""
        mock_result = Mock(name="command_result")
        self.client_mock.command.return_value = mock_result

        result = command("SHOW TABLES")

        self.assertEqual(result, mock_result)

    def test_insert_function(self):
        """insert convenience function should delegate to ClickHouseDB.insert."""
        data = [[1, "test"]]
        insert("test_table", data, ["id", "name"])

        self.client_mock.insert.assert_called_once()
