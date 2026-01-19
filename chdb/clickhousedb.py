"""ClickHouse 数据库连接和查询封装模块."""

import logging
import threading
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from django.conf import settings

logger = logging.getLogger(__name__)


class ClickHouseDB:
    """
    ClickHouse 数据库封装类.

    使用线程安全的单例模式确保全局只有一个连接实例.
    所有查询和命令都通过这个类进行.
    """

    _instance: Client | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> Client:
        """
        获取 ClickHouse 客户端单例实例(线程安全).

        使用双重检查锁定模式确保线程安全:
        1. 第一次检查(无锁): 快速返回已存在的实例
        2. 获取锁: 确保只有一个线程创建实例
        3. 第二次检查(有锁): 防止多个线程同时创建实例

        Returns:
            Client: clickhouse-connect 客户端实例

        Raises:
            Exception: 连接失败时抛出异常

        """
        # 第一次检查（无锁）- 快速路径
        if cls._instance is None:
            # 获取锁
            with cls._lock:
                # 第二次检查（有锁）- 防止竞态条件
                if cls._instance is None:
                    try:
                        cls._instance = clickhouse_connect.get_client(
                            host=settings.CLICKHOUSE_HOST,
                            port=settings.CLICKHOUSE_PORT,
                            username=settings.CLICKHOUSE_USER,
                            password=settings.CLICKHOUSE_PASSWORD,
                            database=settings.CLICKHOUSE_DATABASE,
                            secure=settings.CLICKHOUSE_SECURE,
                        )
                        logger.info(
                            "ClickHouse 连接成功: %s:%s/%s",
                            settings.CLICKHOUSE_HOST,
                            settings.CLICKHOUSE_PORT,
                            settings.CLICKHOUSE_DATABASE,
                        )
                    except Exception as e:
                        logger.error("ClickHouse 连接失败: %s", e)
                        raise

        return cls._instance

    @classmethod
    def reset_connection(cls) -> None:
        """
        重置连接(线程安全).

        关闭当前连接并清空实例, 下次调用 get_instance() 时会重新创建连接.
        用于测试或需要重新连接的场景.
        """
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.close()
                    logger.info("ClickHouse 连接已关闭")
                except Exception as e:
                    logger.warning("关闭 ClickHouse 连接时出错: %s", e)
                finally:
                    cls._instance = None

    @classmethod
    def query(
        cls,
        query_sql: str,
        parameters: dict[str, Any] | None = None,
        settings_dict: dict[str, Any] | None = None,
    ) -> Any:
        """
        执行查询语句并返回结果.

        Args:
            query_sql: SQL 查询语句
            parameters: 查询参数字典, 用于参数化查询
            settings_dict: ClickHouse 查询设置

        Returns:
            查询结果对象, 可以使用以下方法访问数据:
            - result.result_rows: 返回行列表
            - result.result_columns: 返回列数据
            - result.column_names: 返回列名列表
            - result.first_row: 返回第一行
            - result.first_item: 返回第一个值

        Example:
            result = ClickHouseDB.query("SELECT * FROM users WHERE id = {id:UInt32}", {"id": 1})
            for row in result.result_rows:
                print(row)

        """
        client = cls.get_instance()
        try:
            logger.info("执行查询: %s, 参数: %s", query_sql, parameters)
            return client.query(
                query_sql, parameters=parameters, settings=settings_dict
            )
        except Exception as e:
            logger.error("查询执行失败: %s, SQL: %s", e, query_sql)
            raise

    @classmethod
    def command(
        cls,
        cmd: str,
        parameters: dict[str, Any] | None = None,
        settings_dict: dict[str, Any] | None = None,
    ) -> Any:
        """
        执行命令 (DDL/DML).

        用于执行不返回结果集的命令, 如 CREATE, DROP, INSERT 等.

        Args:
            cmd: 命令字符串
            parameters: 命令参数字典
            settings_dict: ClickHouse 设置

        Returns:
            命令执行的摘要信息

        Example:
            ClickHouseDB.command("CREATE TABLE test (id UInt32) ENGINE = Memory")
            ClickHouseDB.command("INSERT INTO test VALUES (1)")

        """
        client = cls.get_instance()
        try:
            logger.debug("执行命令: %s, 参数: %s", cmd, parameters)
            return client.command(cmd, parameters=parameters, settings=settings_dict)
        except Exception as e:
            logger.error("命令执行失败: %s, CMD: %s", e, cmd)
            raise

    @classmethod
    def insert(
        cls,
        table: str,
        data: list[list[Any]],
        column_names: list[str] | None = None,
        settings_dict: dict[str, Any] | None = None,
    ) -> Any:
        """
        插入数据到表.

        Args:
            table: 表名
            data: 数据列表, 每个元素是一行数据
            column_names: 列名列表, 如果为 None 则使用表的所有列
            settings_dict: ClickHouse 设置

        Returns:
            插入操作的摘要信息

        Example:
            data = [
                [1, 'Alice', 25],
                [2, 'Bob', 30]
            ]
            ClickHouseDB.insert('users', data, column_names=['id', 'name', 'age'])

        """
        client = cls.get_instance()
        try:
            logger.debug("插入数据到表 %s, 行数: %s", table, len(data))
            return client.insert(
                table, data, column_names=column_names, settings=settings_dict
            )
        except Exception as e:
            logger.error("数据插入失败: %s, 表: %s", e, table)
            raise

    @classmethod
    def query_df(
        cls,
        query_sql: str,
        parameters: dict[str, Any] | None = None,
        settings_dict: dict[str, Any] | None = None,
    ) -> Any:
        """
        执行查询并返回 Pandas DataFrame.

        需要安装 pandas 库才能使用此方法.

        Args:
            query_sql: SQL 查询语句
            parameters: 查询参数字典
            settings_dict: ClickHouse 查询设置

        Returns:
            pandas.DataFrame: 查询结果的 DataFrame

        Example:
            df = ClickHouseDB.query_df("SELECT * FROM users LIMIT 10")
            print(df.head())

        """
        client = cls.get_instance()
        try:
            logger.debug("执行查询并返回 DataFrame: %s", query_sql)
            return client.query_df(
                query_sql, parameters=parameters, settings=settings_dict
            )
        except Exception as e:
            logger.error("查询 DataFrame 失败: %s, SQL: %s", e, query_sql)
            raise

    @classmethod
    def query_arrow(
        cls,
        query_sql: str,
        parameters: dict[str, Any] | None = None,
        settings_dict: dict[str, Any] | None = None,
    ) -> Any:
        """
        执行查询并返回 PyArrow Table.

        需要安装 pyarrow 库才能使用此方法.

        Args:
            query_sql: SQL 查询语句
            parameters: 查询参数字典
            settings_dict: ClickHouse 查询设置

        Returns:
            pyarrow.Table: 查询结果的 Arrow Table

        Example:
            table = ClickHouseDB.query_arrow("SELECT * FROM users")
            print(table.schema)

        """
        client = cls.get_instance()
        try:
            logger.debug("执行查询并返回 Arrow Table: %s", query_sql)
            return client.query_arrow(
                query_sql, parameters=parameters, settings=settings_dict
            )
        except Exception as e:
            logger.error("查询 Arrow Table 失败: %s, SQL: %s", e, query_sql)
            raise

    @classmethod
    def ping(cls) -> bool:
        """
        测试连接是否正常.

        Returns:
            bool: 连接正常返回 True, 否则返回 False

        """
        try:
            client = cls.get_instance()
            client.ping()
            logger.debug("ClickHouse 连接测试成功")
            return True
        except Exception as e:
            logger.error("ClickHouse 连接测试失败: %s", e)
            return False


# 便捷函数, 直接调用类方法


def query(
    query_sql: str,
    parameters: dict[str, Any] | None = None,
    settings_dict: dict[str, Any] | None = None,
) -> Any:
    """
    执行查询语句 (便捷函数).

    Args:
        query_sql: SQL 查询语句
        parameters: 查询参数字典
        settings_dict: ClickHouse 查询设置

    Returns:
        查询结果对象

    """
    return ClickHouseDB.query(query_sql, parameters, settings_dict)


def command(
    cmd: str,
    parameters: dict[str, Any] | None = None,
    settings_dict: dict[str, Any] | None = None,
) -> Any:
    """
    执行命令 (便捷函数).

    Args:
        cmd: 命令字符串
        parameters: 命令参数字典
        settings_dict: ClickHouse 设置

    Returns:
        命令执行的摘要信息

    """
    return ClickHouseDB.command(cmd, parameters, settings_dict)


def insert(
    table: str,
    data: list[list[Any]],
    column_names: list[str] | None = None,
    settings_dict: dict[str, Any] | None = None,
) -> Any:
    """
    插入数据 (便捷函数).

    Args:
        table: 表名
        data: 数据列表
        column_names: 列名列表
        settings_dict: ClickHouse 设置

    Returns:
        插入操作的摘要信息

    """
    return ClickHouseDB.insert(table, data, column_names, settings_dict)
