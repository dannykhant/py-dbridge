"""Tests for loops containing multiple queries."""
import sqlite3
from src.pipeline import run_pipeline

def test_two_queries_in_one_loop(tmp_path):
    code = '''
results = []
for item_id in item_ids:
    cursor.execute("SELECT name FROM items WHERE id = %s", (item_id,))
    name = cursor.fetchone()
    
    cursor.execute("SELECT price FROM prices WHERE item_id = %s", (item_id,))
    price = cursor.fetchone()
    
    results.append((name, price))
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    
    result = run_pipeline(f, None, "postgres", dry_run=True)
    
    assert result.transformations.count("loop_splitting") == 2
    
    transformed_code = result.transformed_code
    
    # We should see two ANY() clauses
    assert "id = ANY(%s)" in transformed_code
    assert "item_id = ANY(%s)" in transformed_code
    
    # Both queries should be batch fetched into distinct result maps
    assert "_pyd_result_map_1 = collections.defaultdict(list)" in transformed_code
    assert "_pyd_result_map_2 = collections.defaultdict(list)" in transformed_code
    
    # Assert correct attribution of result maps and iterators to specific query fetches
    assert "_pyd_iter_1 = iter(_pyd_result_map_1.get(item_id, []))" in transformed_code
    assert "_pyd_iter_2 = iter(_pyd_result_map_2.get(item_id, []))" in transformed_code
    assert "name = next(_pyd_iter_1, None)" in transformed_code
    assert "price = next(_pyd_iter_2, None)" in transformed_code


def test_two_queries_in_one_loop_semantic_equivalence(tmp_path):
    db_path = tmp_path / "multi_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE prices (item_id INTEGER PRIMARY KEY, price INTEGER)")
    conn.executemany("INSERT INTO items VALUES (?, ?)", [(1, "ItemA"), (2, "ItemB"), (3, "ItemC")])
    conn.executemany("INSERT INTO prices VALUES (?, ?)", [(1, 100), (2, 200), (3, 300)])
    conn.commit()
    conn.close()

    db_str = str(db_path).replace('\\', '\\\\')
    code = f'''import sqlite3
conn = sqlite3.connect("{db_str}")
cursor = conn.cursor()
results = []
item_ids = [1, 2, 3]
for item_id in item_ids:
    cursor.execute("SELECT name FROM items WHERE id = ?", (item_id,))
    name = cursor.fetchone()
    
    cursor.execute("SELECT price FROM prices WHERE item_id = ?", (item_id,))
    price = cursor.fetchone()
    
    results.append((name, price))
conn.close()
'''
    src_file = tmp_path / "app.py"
    src_file.write_text(code, encoding="utf-8")
    
    # Run original
    orig_globals = {}
    exec(code, orig_globals)
    orig_results = orig_globals["results"]

    opt_file = tmp_path / "app_opt.py"
    result = run_pipeline(src_file, opt_file, "sqlite", dry_run=False)
    
    assert result.transformations.count("loop_splitting") == 2
    
    opt_code = opt_file.read_text(encoding="utf-8")
    assert "_pyd_iter_1 = iter(_pyd_result_map_1.get(item_id, []))" in opt_code
    assert "_pyd_iter_2 = iter(_pyd_result_map_2.get(item_id, []))" in opt_code
    assert "name = next(_pyd_iter_1, None)" in opt_code
    assert "price = next(_pyd_iter_2, None)" in opt_code
    
    # Run optimized code and verify semantic equivalence
    opt_globals = {}
    exec(opt_code, opt_globals)
    opt_results = opt_globals["results"]
    
    assert orig_results == opt_results
    assert opt_results == [(("ItemA",), (100,)), (("ItemB",), (200,)), (("ItemC",), (300,))]

