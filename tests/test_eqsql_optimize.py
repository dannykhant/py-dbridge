import pytest
from src.scirpy_bridge import eqsql_optimize_query, _shutdown_gateway

@pytest.fixture(autouse=True)
def teardown_gateway():
    yield
    _shutdown_gateway()

def test_live_sqlite_group_by():
    sql = "SELECT id, count(*) FROM orders WHERE user_id = ? GROUP BY id"
    result = eqsql_optimize_query(sql, "sqlite")
    assert "IN ({})" in result
    assert "GROUP BY id" in result

def test_live_no_auto_group_by_c3():
    sql = "SELECT count(*) FROM orders WHERE user_id = ?"
    result = eqsql_optimize_query(sql, "sqlite")
    assert result == "SELECT count(*) FROM orders WHERE user_id IN ({})"
    assert "GROUP BY" not in result

def test_live_postgres_named_param():
    sql = "SELECT count(*) FROM parts WHERE category = %(category)s"
    result = eqsql_optimize_query(sql, "postgres")
    assert "ANY(%(category)s)" in result

def test_live_or_batching():
    sql = "SELECT a FROM t WHERE x = ? OR b = ?"
    result = eqsql_optimize_query(sql, "sqlite")
    assert result.count("IN ({})") == 2

def test_live_mixed_and():
    sql = "SELECT a FROM t WHERE x = ? AND y = 'foo'"
    result = eqsql_optimize_query(sql, "sqlite")
    assert "IN ({})" in result
    assert "y = 'foo'" in result

def test_live_non_equality_param_c1():
    sql = "SELECT a FROM t WHERE x < ? AND y = ?"
    result = eqsql_optimize_query(sql, "sqlite")
    assert "x < ?" in result
    assert "y IN ({})" in result

def test_live_dbtype_routing_c2():
    sql = "SELECT a FROM t WHERE x = %s"
    result = eqsql_optimize_query(sql, "sqlite")
    assert "x IN ({})" in result
    assert "ANY" not in result

def test_live_distinct_c4():
    sql = "SELECT DISTINCT c FROM t WHERE x = ?"
    result = eqsql_optimize_query(sql, "sqlite")
    assert "SELECT DISTINCT c" in result
    assert "x IN ({})" in result

def test_live_param_on_lhs_c5():
    sql = "SELECT a FROM t WHERE ? = x"
    result = eqsql_optimize_query(sql, "postgres")
    assert "x = ANY(%s)" in result
