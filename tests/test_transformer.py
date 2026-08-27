"""Tests for the transformation engine (loop splitting)."""
import ast
from src.transformer import apply_transformations
from src.analyzer import run_analysis
from src.code_generator import generate_code

def test_simple_loop_splitting(tmp_path):
    """Test the DBridge transformation: loop -> collect params + batch query + process results."""
    code = '''
results = []
for product_id in product_ids:
    cursor.execute("SELECT name, price FROM products WHERE id = %s", (product_id,))
    row = cursor.fetchone()
    results.append(row)
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    transformed_ir = apply_transformations(analysis, "postgres")
    
    assert "loop_splitting" in transformed_ir.applied_rules
    transformed_code = generate_code(transformed_ir)
    assert "_pyd_params" in transformed_code and "= [product_id for product_id in product_ids]" in transformed_code
    assert "id = ANY(%s)" in transformed_code
    assert "collections.defaultdict(list)" in transformed_code
    assert "row = next(_pyd_iter" in transformed_code or "next(iter(_pyd_result_map" in transformed_code

def test_while_loop_splitting(tmp_path):
    """Test while loop splitting with state saving/resetting."""
    code = '''
category = 10
results = []
while category != -1:
    cursor.execute("SELECT name, parent FROM category WHERE id = %s", (category,))
    row = cursor.fetchone()
    results.append(row)
    category = get_parent(category)
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    transformed_ir = apply_transformations(analysis, "postgres")
    
    assert "loop_splitting" in transformed_ir.applied_rules
    transformed_code = generate_code(transformed_ir)
    # Check that phase 1 collects params
    assert "_pyd_ctx" in transformed_code and ".append(category)" in transformed_code
    assert "category = get_parent(category)" in transformed_code
    # Check that phase 2 iterates over _pyd_ctx
    assert "for category in _pyd_ctx" in transformed_code
    # Check that ADVANCE is removed from phase 2
    assert transformed_code.count("category = get_parent(category)") == 1
    assert "row = next(_pyd_iter" in transformed_code or "next(iter(_pyd_result_map" in transformed_code

def test_conditional_loop_splitting(tmp_path):
    """Test loop splitting when query execute is inside an if block."""
    code = '''
for pid in product_ids:
    if is_active(pid):
        cursor.execute("SELECT name FROM products WHERE id = %s", (pid,))
        row = cursor.fetchone()
        results.append(row)
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    transformed_ir = apply_transformations(analysis, "postgres")
    
    assert "loop_splitting" in transformed_ir.applied_rules
    transformed_code = generate_code(transformed_ir)
    # Guard should be present in Phase 1
    assert "if is_active(pid):" in transformed_code
    assert "_pyd_params" in transformed_code and ".append(pid)" in transformed_code
    
    # Guard should be present in Phase 2 iterating over the full loop domain
    assert "for pid in product_ids:" in transformed_code
    assert "row = next(_pyd_iter" in transformed_code or "next(iter(_pyd_result_map" in transformed_code

def test_conditional_for_loop_with_else_and_trailing(tmp_path):
    """Test merge-back conditional logic in for loop with else branch and trailing statements."""
    code = '''
for pid in product_ids:
    if is_active(pid):
        cursor.execute("SELECT name, price FROM products WHERE id = %s", (pid,))
        row = cursor.fetchone()
        results.append(row)
    else:
        results.append(None)
    total_processed += 1
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    transformed_ir = apply_transformations(analysis, "postgres")
    
    assert "loop_splitting" in transformed_ir.applied_rules
    transformed_code = generate_code(transformed_ir)
    # Phase 1 collects params
    assert "_pyd_params_1.append(pid)" in transformed_code
    # Phase 2 preserves then branch with fetchone replaced, else branch, and trailing statements
    assert "for pid in product_ids:" in transformed_code
    assert "if is_active(pid):" in transformed_code
    assert "row = next(_pyd_iter_1, None)" in transformed_code
    assert "results.append(None)" in transformed_code
    assert "total_processed += 1" in transformed_code

def test_conditional_while_loop_with_else_and_trailing(tmp_path):
    """Test merge-back conditional logic in while loop with else branch and trailing statements."""
    code = '''
i = 0
while i < len(pids):
    pid = pids[i]
    if is_active(pid):
        cursor.execute("SELECT name FROM products WHERE id = %s", (pid,))
        row = cursor.fetchone()
        results.append(row)
    else:
        results.append(None)
    total += 1
    i += 1
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    transformed_ir = apply_transformations(analysis, "postgres")
    
    assert "loop_splitting" in transformed_ir.applied_rules
    transformed_code = generate_code(transformed_ir)
    # Phase 1 captures domain in _pyd_ctx and params in _pyd_params
    assert "_pyd_ctx_1.append(pid)" in transformed_code
    assert "_pyd_params_1.append(pid)" in transformed_code
    # Phase 2 iterates over _pyd_ctx and preserves if, else, and trailing statement (total += 1)
    assert "for pid in _pyd_ctx_1:" in transformed_code
    assert "if is_active(pid):" in transformed_code
    assert "row = next(_pyd_iter_1, None)" in transformed_code
    assert "results.append(None)" in transformed_code
    assert "total += 1" in transformed_code

def test_dml_rowcount_dependency_not_transformed(tmp_path):
    """Test that DML with rowcount result dependency is not transformed."""
    code = '''
for pid in product_ids:
    cursor.execute("UPDATE products SET price = 100 WHERE id = %s", (pid,))
    n = cursor.rowcount
    updated_counts.append(n)
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, f)
    assert len(analysis.transformable_queries) == 0
    transformed_ir = apply_transformations(analysis, "postgres")
    assert transformed_ir.applied_rules == []
    transformed_code = generate_code(transformed_ir)
    assert "executemany" not in transformed_code

