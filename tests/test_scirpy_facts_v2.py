import json
import os
from pathlib import Path
from src.scirpy_facts import load_scirpy_facts, ScirpyFactsV2
from src.dependency import DependencyAnalyzer
import ast

def test_load_scirpy_facts():
    golden_path = Path(__file__).parent / "fixtures" / "facts_v2_golden.json"
    with open(golden_path, "r") as f:
        data = json.load(f)
        
    facts = load_scirpy_facts(data)
    assert isinstance(facts, ScirpyFactsV2)
    assert len(facts.classes) == 1
    assert facts.classes[0].name == "TestClass"
    assert facts.classes[0].methods[0].name == "test_method"
    assert facts.classes[0].methods[0].methodSummary is not None
    assert facts.classes[0].methods[0].methodSummary.get("hasFetch") is True
    
    assert len(facts.loops) == 1
    loop = facts.loops[0]
    assert loop.method == "test_method"
    assert loop.headLineno == 12
    assert loop.testVars == ["x"]
    assert loop.stmtOrder == [13, 14, 15]
    assert len(loop.deps) == 1
    assert loop.deps[0]["variable"] == "row"
    
    assert len(loop.queries) == 1
    query = loop.queries[0]
    assert query.callLineno == 14
    assert not query.cyclic
    assert query.labels == {"13": "PRE", "14": "EXEC", "15": "POST"}
    assert query.stmtOrder == [13, 14, 15]
    assert len(query.deps) == 1
    
    assert facts.stmtOrder == [13, 14, 15]
    assert len(facts.deps) == 1

def test_classify_loop_stmts_with_scirpy_facts():
    # Setup dummy AST and facts
    stmt_pre = ast.parse("x = 1").body[0]
    stmt_pre.lineno = 13
    
    stmt_exec = ast.parse("cursor.execute('SELECT * FROM users')").body[0]
    stmt_exec.lineno = 14
    
    stmt_post = ast.parse("y = cursor.fetchone()").body[0]
    stmt_post.lineno = 15
    
    body = [stmt_pre, stmt_exec, stmt_post]
    
    golden_path = Path(__file__).parent / "fixtures" / "facts_v2_golden.json"
    with open(golden_path, "r") as f:
        data = json.load(f)
    
    facts = load_scirpy_facts(data)
    
    dep_analyzer = DependencyAnalyzer()
    
    labels = dep_analyzer.classify_loop_stmts(
        body=body,
        execute_node=stmt_exec.value,
        scirpy_facts=facts
    )
    
    assert labels == ["PRE", "EXEC", "POST"]

def test_classify_loop_stmts_with_pdg_deps():
    stmt_pre = ast.parse("x = 1").body[0]
    stmt_pre.lineno = 10
    stmt_exec = ast.parse("cursor.execute('SELECT * FROM users')").body[0]
    stmt_exec.lineno = 11
    stmt_post = ast.parse("print(x)").body[0]
    stmt_post.lineno = 12
    
    body = [stmt_pre, stmt_exec, stmt_post]
    
    facts_dict = {
        "loops": [{
            "method": "foo",
            "headLineno": 9,
            "queries": [{
                "callLineno": 11,
                "cyclic": False,
                "labels": {},
                "deps": [{"source": 11, "target": 12, "type": "flow"}]
            }]
        }]
    }
    facts = load_scirpy_facts(facts_dict)
    dep_analyzer = DependencyAnalyzer()
    labels = dep_analyzer.classify_loop_stmts(
        body=body,
        execute_node=stmt_exec.value,
        scirpy_facts=facts
    )
    assert labels == ["PRE", "EXEC", "POST"]

def test_has_cyclic_dependency_with_scirpy_facts():
    stmt_pre = ast.parse("x = 1").body[0]
    stmt_pre.lineno = 13
    
    stmt_exec = ast.parse("cursor.execute('SELECT * FROM users')").body[0]
    stmt_exec.lineno = 14
    
    stmt_post = ast.parse("y = cursor.fetchone()").body[0]
    stmt_post.lineno = 15
    
    body = [stmt_pre, stmt_exec, stmt_post]
    
    golden_path = Path(__file__).parent / "fixtures" / "facts_v2_golden.json"
    with open(golden_path, "r") as f:
        data = json.load(f)
    
    facts = load_scirpy_facts(data)
    
    dep_analyzer = DependencyAnalyzer()
    has_cyclic = dep_analyzer.has_cyclic_dependency(
        execute_node=stmt_exec.value,
        body=body,
        param_vars=["x"],
        scirpy_facts=facts
    )
    
    # from golden facts: has_cyclic_dependency is false
    assert not has_cyclic

def test_has_cyclic_defensive_or():
    # Even if SCIRPy says cyclic=False, if python sees transitive cyclic dependency, it returns True
    code = """
while node is not None:
    cursor.execute("SELECT parent FROM tree WHERE id = %s", (node,))
    row = cursor.fetchone()
    node = row[0]
"""
    tree = ast.parse(code)
    loop = tree.body[0]
    exec_node = loop.body[0].value
    
    facts_dict = {
        "loops": [{
            "method": "foo",
            "headLineno": 2,
            "queries": [{
                "callLineno": getattr(exec_node, "lineno", -1),
                "cyclic": False,
                "labels": {}
            }]
        }]
    }
    facts = load_scirpy_facts(facts_dict)
    dep_analyzer = DependencyAnalyzer()
    has_cyclic = dep_analyzer.has_cyclic_dependency(
        execute_node=exec_node,
        body=loop.body,
        param_vars=["node"],
        scirpy_facts=facts
    )
    assert has_cyclic is True

def test_transformer_uses_stmt_order(tmp_path):
    from src.transformer import apply_transformations
    from src.analyzer import run_analysis
    from src.code_generator import generate_code

    code = '''
results = []
for product_id in product_ids:
    a = 1
    b = 2
    cursor.execute("SELECT name, price FROM products WHERE id = %s", (product_id,))
    row = cursor.fetchone()
    results.append(row)
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    os.environ["PYDBRIDGE_NO_SCIRPY"] = "1"
    analysis = run_analysis({}, f)
    del os.environ["PYDBRIDGE_NO_SCIRPY"]
    
    # Inject stmtOrder that reverses pre statements: b=2 before a=1
    analysis.stmtOrder = [5, 4]
    transformed_ir = apply_transformations(analysis, "postgres")
    code_out = generate_code(transformed_ir)
    idx_b = code_out.find("b = 2")
    idx_a = code_out.find("a = 1")
    assert idx_b != -1 and idx_a != -1
    assert idx_b < idx_a

def test_analysis_result_fields(tmp_path):
    from src.analyzer import run_analysis
    code = '''
for pid in pids:
    cursor.execute("SELECT * FROM users WHERE id = %s", (pid,))
    row = cursor.fetchone()
'''
    f = tmp_path / "app.py"
    f.write_text(code, encoding="utf-8")
    os.environ["PYDBRIDGE_NO_SCIRPY"] = "1"
    analysis = run_analysis({}, f)
    del os.environ["PYDBRIDGE_NO_SCIRPY"]
    
    assert hasattr(analysis, "deps")
    assert hasattr(analysis, "labels")
    assert hasattr(analysis, "cyclic")
    assert hasattr(analysis, "stmtOrder")
    assert hasattr(analysis, "stmt_order")
    assert isinstance(analysis.deps, list)
    assert isinstance(analysis.labels, dict)
    assert isinstance(analysis.cyclic, bool)
    assert isinstance(analysis.stmtOrder, list)
    assert isinstance(analysis.stmt_order, list)

def test_degraded_no_scirpy_fallback():
    os.environ["PYDBRIDGE_NO_SCIRPY"] = "1"
    from src.scirpy_bridge import run_scirpy_analysis
    
    result = run_scirpy_analysis(Path("dummy.json"), "dummy", Path("/tmp"), Path("/tmp"))
    assert result == {"facts": {}, "analysis_json_path": None, "opt_code_path": None}
    
    # Cleanup
    del os.environ["PYDBRIDGE_NO_SCIRPY"]

def test_golden_facts_transformation_pipeline(tmp_path):
    from src.transformer import apply_transformations
    from src.analyzer import AnalysisResult
    from src.patterns import QueryInLoop
    from src.code_generator import generate_code

    golden_path = Path(__file__).parent / "fixtures" / "facts_v2_golden.json"
    with open(golden_path, "r") as f:
        facts_data = json.load(f)
    facts = load_scirpy_facts(facts_data)

    code = '''
x = [1, 2, 3]
for item in x:
    cursor.execute("SELECT name, price FROM products WHERE id = %s", (item,))
    row = cursor.fetchone()
    print(row)
'''
    tree = ast.parse(code)
    loop = tree.body[1]
    exec_call = loop.body[0].value

    query = QueryInLoop(
        loop_node=loop,
        execute_node=exec_call,
        query_string="SELECT name, price FROM products WHERE id = %s",
        parameter_vars=["item"],
        loop_var="item",
        line_number=3,
        has_result_dependency=True,
        is_dml=False
    )
    exec_call.lineno = 14
    loop.body[0].lineno = 14
    loop.body[1].lineno = 15

    analysis = AnalysisResult(
        queries_in_loops=[query],
        dependencies=[],
        transformable_queries=[query],
        scirpy_facts=facts,
        tree=tree,
        stmtOrder=[13, 14, 15]
    )

    transformed_ir = apply_transformations(analysis, "postgres")
    assert "loop_splitting" in transformed_ir.applied_rules
    out = generate_code(transformed_ir)
    assert "id = ANY(%s)" in out
    assert "next(_pyd_iter" in out


