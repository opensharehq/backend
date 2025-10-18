"""ClickHouse 数据库集成测试."""

import logging

logger = logging.getLogger()


def real_world_test():
    """测试 ClickHouse 连接和查询功能(使用类方法)."""
    from chdb.clickhousedb import ClickHouseDB

    db = ClickHouseDB.get_instance()
    result = db.query("SELECT * FROM name_info LIMIT 10")
    logger.info(result.result_set)


def real_world_test2():
    """测试 ClickHouse 连接和查询功能(使用便捷函数)."""
    from chdb.clickhousedb import query

    result = query("SELECT * FROM name_info LIMIT 10")
    logger.info(result.result_set)
