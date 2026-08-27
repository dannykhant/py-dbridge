import pytest
import ast
from src.analyzer import run_analysis
from src.transformer import apply_transformations
from src.code_generator import generate_code

def run_transform(tmp_path, code, dialect="postgres"):
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    transformed_ir = apply_transformations(analysis, dialect)
    return generate_code(transformed_ir)

def test_keyed_projection(tmp_path):
    code = '''
for product_id in product_ids:
    cursor.execute("SELECT name, price FROM products WHERE id = %s", (product_id,))
    row = cursor.fetchone()
    print(row)
'''
    transformed = run_transform(tmp_path, code)
    assert "SELECT id, name, price FROM products WHERE id = ANY(%s)" in transformed
    assert "row = next(_pyd_iter" in transformed

def test_aggregate_group_by_batching(tmp_path):
    code = '''
for category in categories:
    cursor.execute("SELECT count(partkey) FROM parts WHERE category = %s", (category,))
    row = cursor.fetchone()
'''
    transformed = run_transform(tmp_path, code)
    assert "SELECT category, count(partkey) FROM parts WHERE category = ANY(%s) GROUP BY category" in transformed

def test_dml_executemany_loop_batching(tmp_path):
    code = '''
for product_id, stock_reduction in items:
    cursor.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (stock_reduction, product_id))
'''
    transformed = run_transform(tmp_path, code)
    assert "cursor.executemany" in transformed
    assert "UPDATE products SET stock = stock - %s WHERE id = %s" in transformed

def test_multi_row_fetchall_preservation(tmp_path):
    code = '''
for category in categories:
    cursor.execute("SELECT name FROM products WHERE category = %s", (category,))
    rows = cursor.fetchall()
'''
    transformed = run_transform(tmp_path, code)
    assert "rows = _pyd_result_map" in transformed and ".get(category, [])" in transformed

def test_guarded_query_execution(tmp_path):
    code = '''
for product_id in product_ids:
    if product_id % 2 == 0:
        cursor.execute("SELECT name, price FROM products WHERE id = %s", (product_id,))
        row = cursor.fetchone()
        print(row)
'''
    transformed = run_transform(tmp_path, code)
    assert "if product_id % 2 == 0:" in transformed
    assert "SELECT id, name, price FROM products WHERE id = ANY(%s)" in transformed
    assert "for product_id in product_ids:" in transformed
    assert "row = next(_pyd_iter" in transformed

def test_transitive_cyclic_negative_case(tmp_path):
    code = '''
curr = 1
while curr is not None:
    cursor.execute("SELECT parent_id FROM nodes WHERE id = %s", (curr,))
    row = cursor.fetchone()
    if row and row[0] is not None:
        curr = row[0]
    else:
        curr = None
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    assert analysis.cyclic is True
    assert len(analysis.transformable_queries) == 0
    transformed_ir = apply_transformations(analysis, "postgres")
    assert transformed_ir.applied_rules == []
    transformed = generate_code(transformed_ir)
    assert "ANY(%s)" not in transformed

def test_scirpy_facts_driven_cyclic_suppression(tmp_path):
    from src.scirpy_facts import load_scirpy_facts
    code = '''
for pid in product_ids:
    cursor.execute("SELECT name FROM products WHERE id = %s", (pid,))
    row = cursor.fetchone()
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    
    # Inject SCIRPy facts declaring this query cyclic
    facts_dict = {
        "loops": [{
            "method": "foo",
            "headLineno": 2,
            "queries": [{
                "callLineno": 3,
                "cyclic": True,
                "labels": {"2": "PRE", "3": "EXEC", "4": "POST"}
            }]
        }]
    }
    analysis.scirpy_facts = load_scirpy_facts(facts_dict)
    analysis.cyclic = True
    analysis.transformable_queries = []
    
    transformed_ir = apply_transformations(analysis, "postgres")
    assert transformed_ir.applied_rules == []

def test_scirpy_facts_driven_labels_and_order(tmp_path):
    from src.scirpy_facts import load_scirpy_facts
    code = '''
for pid in product_ids:
    a = 1
    b = 2
    cursor.execute("SELECT name FROM products WHERE id = %s", (pid,))
    row = cursor.fetchone()
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    
    # Custom SCIRPy statement order (b=2 before a=1)
    facts_dict = {
        "loops": [{
            "method": "foo",
            "headLineno": 2,
            "queries": [{
                "callLineno": 5,
                "cyclic": False,
                "stmtOrder": [4, 3, 5, 6],
                "labels": {"3": "PRE", "4": "PRE", "5": "EXEC", "6": "POST"}
            }]
        }]
    }
    analysis.scirpy_facts = load_scirpy_facts(facts_dict)
    transformed_ir = apply_transformations(analysis, "postgres")
    assert "loop_splitting" in transformed_ir.applied_rules
    out = generate_code(transformed_ir)
    assert out.find("b = 2") < out.find("a = 1")
