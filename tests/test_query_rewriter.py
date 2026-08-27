"""Tests for SQL query rewriting."""
from src.query_rewriter import QueryRewriter

def test_simple_equality_to_any():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT name, price FROM products WHERE id = %s",
        param_column="id",
        db_type="postgres"
    )
    assert "ANY" in result
    assert "id = ANY(%s)" in result

def test_preserves_other_predicates():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT name FROM products WHERE id = %s AND active = true",
        param_column="id",
        db_type="postgres"
    )
    assert "ANY" in result
    assert "active = true" in result

def test_sqlite_rewrite():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT count(*) FROM parts WHERE category = ?",
        param_column="category",
        db_type="sqlite"
    )
    assert "IN ({})" in result


def test_key_already_in_select_index_0():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT id, name, price FROM products WHERE id = %s",
        param_column="id",
        db_type="postgres"
    )
    assert result.key_index == 0
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT id, name, price" in result.sql


def test_key_already_in_select_index_1():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT name, id, price FROM products WHERE id = %s",
        param_column="id",
        db_type="postgres"
    )
    assert result.key_index == 1
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT name, id, price" in result.sql


def test_key_not_in_select_prepended():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT name, price FROM products WHERE id = %s",
        param_column="id",
        db_type="postgres"
    )
    assert result.key_index == 0
    assert result.key_prepended is True
    assert result.payload_slice == slice(1, None)
    assert "SELECT id, name, price" in result.sql


def test_key_wildcard_prepended():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT * FROM products WHERE id = ?",
        param_column="id",
        db_type="sqlite"
    )
    assert result.key_index == 0
    assert result.key_prepended is True
    assert result.payload_slice == slice(1, None)
    assert "SELECT id, *" in result.sql


def test_aliased_column_in_select_index_0():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT id AS item_id, name FROM products WHERE id = %s",
        param_column="id",
        db_type="postgres"
    )
    assert result.key_index == 0
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT id AS item_id, name" in result.sql
    assert "id = ANY(%s)" in result.sql


def test_qualified_and_aliased_column_matched_by_alias():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT p.id AS item_id, p.name FROM products p WHERE item_id = %s",
        param_column="item_id",
        db_type="postgres"
    )
    assert result.key_index == 0
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT p.id AS item_id, p.name" in result.sql
    assert "item_id = ANY(%s)" in result.sql


def test_qualified_and_aliased_column_matched_by_qualified_name():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT p.id AS item_id, p.name FROM products p WHERE p.id = %s",
        param_column="p.id",
        db_type="postgres"
    )
    assert result.key_index == 0
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT p.id AS item_id, p.name" in result.sql
    assert "p.id = ANY(%s)" in result.sql


def test_qualified_column_without_alias():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT p.item_id, p.name FROM products p WHERE item_id = %s",
        param_column="item_id",
        db_type="postgres"
    )
    assert result.key_index == 0
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT p.item_id, p.name" in result.sql
    assert "item_id = ANY(%s)" in result.sql


def test_aliased_column_at_index_1():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT name, p.id AS item_id, price FROM products p WHERE item_id = %s",
        param_column="item_id",
        db_type="postgres"
    )
    assert result.key_index == 1
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT name, p.id AS item_id, price" in result.sql
    assert "item_id = ANY(%s)" in result.sql


def test_sqlite_qualified_aliased_column():
    rewriter = QueryRewriter()
    result = rewriter.rewrite_for_batch(
        "SELECT p.id AS item_id, p.name FROM products p WHERE p.id = ?",
        param_column="p.id",
        db_type="sqlite"
    )
    assert result.key_index == 0
    assert result.key_prepended is False
    assert result.payload_slice is None
    assert "SELECT p.id AS item_id, p.name" in result.sql
    assert "p.id IN ({})" in result.sql


