"""End-to-end tests: transform code and verify semantic equivalence.

These tests run both original and transformed code against a database
to verify that results are identical.
"""
import sqlite3
import pytest
from src.pipeline import run_pipeline
from pathlib import Path

@pytest.fixture
def test_db(tmp_path):
    """Create a test SQLite database with sample data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price INTEGER)")
    conn.executemany("INSERT INTO products VALUES (?, ?, ?)", [
        (1, "Notebook", 1299), (2, "Pencil", 799), (3, "Lamp", 2499),
    ])
    conn.commit()
    conn.close()
    return db_path

def test_transform_preserves_semantics(tmp_path, test_db):
    """The transformed program must produce identical results to the original."""
    source = tmp_path / "app.py"
    db_str = str(test_db).replace('\\', '\\\\')
    source.write_text(f'''
import sqlite3
conn = sqlite3.connect("{db_str}")
cursor = conn.cursor()
results = []
product_ids = [1, 2, 3]
for pid in product_ids:
    cursor.execute("SELECT id, name, price FROM products WHERE id = ?", (pid,))
    row = cursor.fetchone()
    results.append(row)
conn.close()
''', encoding="utf-8")
    
    # Run original code
    orig_globals = {}
    exec(source.read_text(encoding="utf-8"), orig_globals)
    orig_results = orig_globals["results"]
    
    # Transform using pipeline
    output = tmp_path / "app_opt.py"
    run_pipeline(source, output, "sqlite", dry_run=False)
    
    # Run optimized code
    opt_globals = {}
    exec(output.read_text(encoding="utf-8"), opt_globals)
    opt_results = opt_globals["results"]
    
    assert orig_results == opt_results
    
    opt_code = output.read_text(encoding="utf-8")
    assert "IN ({})" in opt_code
