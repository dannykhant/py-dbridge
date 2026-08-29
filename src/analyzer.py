"""Static analysis coordinator.

Combines:
1. Python-side AST pattern detection (fast, lightweight)
2. SCIRPy Java-based deep analysis (CFG, data flow) via subprocess
"""
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from src.patterns import QueryPatternDetector, QueryInLoop
from src.dependency import DependencyAnalyzer, Dependency
from src.scirpy_facts import load_scirpy_facts, ScirpyFactsV2

@dataclass
class StmtFacts:
    """Facts extracted from SCIRPy analysis for a single statement."""
    lineno: int
    defs: list[str]
    uses: list[str]
    live_before: list[str]

@dataclass
class AnalysisResult:
    """Results from static analysis."""
    queries_in_loops: list[QueryInLoop]
    dependencies: list[Dependency]
    transformable_queries: list[QueryInLoop]
    scirpy_analysis: dict | None = None
    scirpy_facts: ScirpyFactsV2 | None = None
    stmt_facts: dict[int, StmtFacts] | None = None
    opt_code_path: str | None = None
    tree: ast.AST = None
    deps: list[Any] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    cyclic: bool = False
    stmtOrder: list[int] = field(default_factory=list)

    @property
    def stmt_order(self) -> list[int]:
        return self.stmtOrder

    @property
    def engine(self) -> str:
        """Name of the analysis engine used ('scirpy' or 'degraded')."""
        return "scirpy"

    def format_summary(self, applied_transformations: list[str] | None = None) -> str:
        """Return a formatted summary box for CLI output."""
        engine_str = "SCIRPy (Java Static Analysis)"
        total_queries = len(self.queries_in_loops)
        transformable = len(self.transformable_queries)
        cyclic_str = "Yes (preserves iterative execution)" if self.cyclic else "No"
        if applied_transformations:
            seen = set()
            distinct_rules = [r for r in applied_transformations if not (r in seen or seen.add(r))]
            rules_str = ", ".join(distinct_rules)
        else:
            rules_str = "None"

        lines = [
            "===================== Analysis Result =====================",
            f"  Analysis Engine       : {engine_str}",
            f"  Queries in Loops      : {total_queries} ({transformable} transformable)",
            f"  Cyclic Dependency     : {cyclic_str}",
            f"  Applied Rules         : {rules_str}",
            "===========================================================",
        ]
        return "\n".join(lines)

def extract_stmt_facts(facts_json: dict) -> dict[int, StmtFacts]:
    result = {}
    if not facts_json or "classes" not in facts_json:
        return result
    for cls in facts_json.get("classes", []):
        for method in cls.get("methods", []):
            for stmt in method.get("statements", []):
                lineno = stmt.get("lineno")
                if lineno is not None and lineno > 0:
                    result[lineno] = StmtFacts(
                        lineno=lineno,
                        defs=stmt.get("defs", []),
                        uses=stmt.get("uses", []),
                        live_before=stmt.get("liveBefore", [])
                    )
    return result

def run_analysis(source_path: Path, source_code: str | None = None) -> AnalysisResult:
    """Run combined Python + SCIRPy analysis."""
    if source_code is None:
        source_code = source_path.read_text(encoding="utf-8")
        
    filename = str(source_path)
    source_name = source_path.stem
    tree = ast.parse(source_code, filename=filename)
    
    # 1. Detect query patterns in loops
    detector = QueryPatternDetector()
    queries = detector.detect(tree)
    
    # 2. Invoke SCIRPy Java static analysis
    import json
    from src.scirpy_bridge import run_scirpy_analysis
    from src.ast_to_json import ast_to_dict
    import uuid

    project_root = Path(__file__).resolve().parents[1]
    call_id = uuid.uuid4().hex[:8]
    tmp_dir = project_root / ".scirpy_tmp" / f"{source_path.stem}_{call_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    json_path = tmp_dir / f"{source_path.stem}.json"
    json_path.write_text(
        json.dumps(ast_to_dict(tree), indent=2), encoding="utf-8"
    )
    
    scirpy_result = run_scirpy_analysis(
        json_ast_path=json_path,
        source_name=source_name,
        output_dir=tmp_dir,
        data_dir=project_root / "scirpy" / "parsePythonIR" / "src"
    )
    scirpy_info = {"status": 0, "json_ast_path": str(json_path), "analysis_json_path": scirpy_result.get("analysis_json_path")}
    facts_dict = scirpy_result.get("facts", {})
    stmt_facts = extract_stmt_facts(facts_dict)
    parsed_facts = load_scirpy_facts(facts_dict)
    opt_code_path = scirpy_result.get("opt_code_path")

    # 3. Analyze dependencies for each loop containing a query
    dep_analyzer = DependencyAnalyzer()
    dependencies = []
    transformable_queries = []
    
    for query in queries:
        loop_deps = dep_analyzer.analyze_loop(query.loop_node)
        dependencies.extend(loop_deps)
        
        is_cyclic = dep_analyzer.has_cyclic_dependency(
            query.execute_node,
            query.loop_node.body,
            query.parameter_vars,
            stmt_facts=stmt_facts,
            scirpy_facts=parsed_facts
        )
        if is_cyclic:
            query.is_transformable = False
        if query.is_transformable:
            transformable_queries.append(query)
            
    facts_deps = []
    facts_labels = {}
    facts_stmt_order = []
    facts_cyclic = False
    
    if parsed_facts:
        facts_deps = list(parsed_facts.deps) if parsed_facts.deps else []
        facts_stmt_order = list(parsed_facts.stmtOrder) if parsed_facts.stmtOrder else []
        for l in parsed_facts.loops:
            if not facts_stmt_order and l.stmtOrder:
                facts_stmt_order = list(l.stmtOrder)
            if not facts_deps and l.deps:
                facts_deps = list(l.deps)
            for q in l.queries:
                facts_labels.update(q.labels)
                for py_q in queries:
                    if getattr(py_q.execute_node, 'lineno', -1) == q.callLineno and not py_q.is_transformable:
                        q.cyclic = True
                        l.cyclic = True
                if q.cyclic:
                    facts_cyclic = True
                if not facts_stmt_order and q.stmtOrder:
                    facts_stmt_order = list(q.stmtOrder)
                if not facts_deps and q.deps:
                    facts_deps = list(q.deps)

    is_any_query_cyclic = any(not q.is_transformable for q in queries)
    final_cyclic = bool(facts_cyclic or is_any_query_cyclic)

    return AnalysisResult(
        queries_in_loops=queries,
        dependencies=dependencies,
        transformable_queries=transformable_queries,
        scirpy_analysis=scirpy_info,
        stmt_facts=stmt_facts,
        scirpy_facts=parsed_facts,
        opt_code_path=opt_code_path,
        tree=tree,
        deps=facts_deps,
        labels=facts_labels,
        cyclic=final_cyclic,
        stmtOrder=facts_stmt_order
    )

