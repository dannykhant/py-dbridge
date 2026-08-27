"""Tests for query pattern detection."""
import ast
from src.patterns import QueryPatternDetector

def test_detect_execute_in_for_loop():
    code = '''
for pid in product_ids:
    cursor.execute("SELECT name FROM products WHERE id = %s", (pid,))
    row = cursor.fetchone()
'''
    tree = ast.parse(code)
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    assert len(queries) == 1
    assert queries[0].line_number == 3
    assert "pid" in queries[0].parameter_vars

def test_detect_execute_in_while_loop():
    code = '''
while category != -1:
    cursor.execute("SELECT count(*) FROM parts WHERE cat = %s", (category,))
    row = cursor.fetchone()
    category = get_parent(category)
'''
    tree = ast.parse(code)
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    assert len(queries) == 1

def test_no_detection_outside_loop():
    code = 'cursor.execute("SELECT * FROM products")'
    tree = ast.parse(code)
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    assert len(queries) == 0

def test_detect_with_conditional():
    code = '''
for pid in product_ids:
    if is_active(pid):
        cursor.execute("SELECT name FROM products WHERE id = %s", (pid,))
        row = cursor.fetchone()
'''
    tree = ast.parse(code)
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    assert len(queries) == 1

def test_detect_dml_with_rowcount_dependency():
    code = '''
for pid in product_ids:
    cursor.execute("UPDATE products SET price = 100 WHERE id = %s", (pid,))
    n = cursor.rowcount
    updated_counts.append(n)
'''
    tree = ast.parse(code)
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    assert len(queries) == 1
    assert queries[0].is_dml is True
    assert queries[0].has_result_dependency is True
    assert queries[0].is_transformable is False

def test_detect_dml_without_result_dependency():
    code = '''
for pid in product_ids:
    cursor.execute("UPDATE products SET price = 100 WHERE id = %s", (pid,))
'''
    tree = ast.parse(code)
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    assert len(queries) == 1
    assert queries[0].is_dml is True
    assert queries[0].has_result_dependency is False
    assert queries[0].is_transformable is True

def test_detect_dml_with_lastrowid_dependency():
    code = '''
for name in names:
    cursor.execute("INSERT INTO products (name) VALUES (%s)", (name,))
    new_id = cursor.lastrowid
    ids.append(new_id)
'''
    tree = ast.parse(code)
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    assert len(queries) == 1
    assert queries[0].is_dml is True
    assert queries[0].has_result_dependency is True
    assert queries[0].is_transformable is False
