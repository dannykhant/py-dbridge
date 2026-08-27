import ast
from pathlib import Path
from src.analyzer import run_analysis, StmtFacts, extract_stmt_facts
from src.dependency import DependencyAnalyzer
from src.pipeline import run_pipeline

def test_extract_stmt_facts():
    facts_json = {
        "classes": [{
            "methods": [{
                "statements": [
                    {
                        "lineno": 10,
                        "defs": ["x"],
                        "uses": ["y"],
                        "liveBefore": ["z"]
                    }
                ]
            }]
        }]
    }
    facts = extract_stmt_facts(facts_json)
    assert 10 in facts
    assert facts[10].defs == ["x"]
    assert facts[10].uses == ["y"]
    assert facts[10].live_before == ["z"]

def test_scirpy_backed_classify_loop_stmts():
    # Construct a simple AST with a query execution
    code = """
while True:
    row = cursor.fetchone()
    if not row:
        break
    y = row[0]
"""
    tree = ast.parse(code)
    loop_node = tree.body[0]
    execute_node = loop_node.body[0].value
    
    analyzer = DependencyAnalyzer()
    
    # Normally this AST walking would detect row as defined from fetchone
    res_no_facts = analyzer.classify_loop_stmts(loop_node.body, execute_node)
    
    # Now provide stmt_facts that override AST logic (e.g. simulate SCIRPy says 'row' isn't used)
    # We'll just provide empty uses and defs for everything except the execute node
    stmt_facts = {
        n.lineno: StmtFacts(lineno=n.lineno, defs=[], uses=[], live_before=[])
        for n in loop_node.body
    }
    stmt_facts[loop_node.body[0].lineno] = StmtFacts(
        lineno=loop_node.body[0].lineno,
        defs=["row"],
        uses=[],
        live_before=[]
    )
    stmt_facts[loop_node.body[2].lineno] = StmtFacts(
        lineno=loop_node.body[2].lineno,
        defs=["y"],
        uses=["row"],
        live_before=[]
    )
    
    res_with_facts = analyzer.classify_loop_stmts(loop_node.body, execute_node, stmt_facts=stmt_facts)
    assert res_with_facts == ['EXEC', 'PRE', 'POST']

def test_pipeline_fallback(tmp_path):
    source_file = tmp_path / "test_source.py"
    source_file.write_text("def foo():\n    for i in range(10):\n        print(i)")
    
    # Run pipeline with a dry run
    result = run_pipeline(source_file, None, db_type="sqlite", dry_run=True)
    
    # Since SCIRPy won't produce a valid Opt_Code path in this isolated test, 
    # it should fallback to the AST unparsed code (or original code if no transform)
    assert "print(i)" in result.transformed_code

def test_live_scirpy_analysis_end_to_end(tmp_path):
    """End-to-end test verifying live SCIRPy returns facts with loops, labels, cyclic flag, and deps."""
    code = '''
category = 10
while category != -1:
    cursor.execute("SELECT name FROM parts WHERE id = %s", (category,))
    row = cursor.fetchone()
    category = get_parent(category)
'''
    source_file = tmp_path / "test_loop.py"
    source_file.write_text(code, encoding="utf-8")
    analysis = run_analysis({}, source_file)
    assert analysis.scirpy_facts is not None
    assert len(analysis.scirpy_facts.loops) > 0
    loop = analysis.scirpy_facts.loops[0]
    assert len(loop.queries) > 0
    query_fact = loop.queries[0]
    assert isinstance(query_fact.labels, dict)
    assert isinstance(query_fact.cyclic, bool)
    assert hasattr(query_fact, "deps")

