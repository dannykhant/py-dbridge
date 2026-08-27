"""Tests for data dependency analysis."""
import ast
from src.dependency import DependencyAnalyzer

def test_no_cyclic_dependency():
    code = '''
for pid in product_ids:
    cursor.execute("SELECT name FROM products WHERE id = %s", (pid,))
    row = cursor.fetchone()
    total += row[0]
'''
    tree = ast.parse(code)
    loop = tree.body[0]
    analyzer = DependencyAnalyzer()
    deps = analyzer.analyze_loop(loop)
    # Check that we can compute dependencies and it's not considered loop-carried on query result
    execute_node = loop.body[0].value
    assert not analyzer.has_cyclic_dependency(execute_node, loop.body, ["pid"])

def test_cyclic_dependency_transitive_closure():
    """Transitive closure queries have cyclic dependencies."""
    code = '''
while node is not None:
    cursor.execute("SELECT parent FROM tree WHERE id = %s", (node,))
    row = cursor.fetchone()
    node = row[0]  # next iteration depends on this query's result
'''
    tree = ast.parse(code)
    loop = tree.body[0]
    analyzer = DependencyAnalyzer()
    
    execute_node = loop.body[0].value
    assert analyzer.has_cyclic_dependency(execute_node, loop.body, ["node"])

