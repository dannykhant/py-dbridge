from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class ScirpyQueryFact:
    callLineno: int
    cyclic: bool = False
    labels: Dict[str, str] = field(default_factory=dict)
    deps: List[Dict[str, Any]] = field(default_factory=list)
    stmtOrder: List[int] = field(default_factory=list)

@dataclass
class ScirpyLoopFact:
    method: str
    headLineno: int
    testVars: List[str] = field(default_factory=list)
    queries: List[ScirpyQueryFact] = field(default_factory=list)
    stmtOrder: List[int] = field(default_factory=list)
    deps: List[Dict[str, Any]] = field(default_factory=list)
    cyclic: bool = False

@dataclass
class ScirpyMethodFact:
    name: str
    methodSummary: Optional[Dict[str, Any]] = None
    statements: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class ScirpyClassFact:
    name: str
    methods: List[ScirpyMethodFact] = field(default_factory=list)

@dataclass
class ScirpyFactsV2:
    classes: List[ScirpyClassFact] = field(default_factory=list)
    loops: List[ScirpyLoopFact] = field(default_factory=list)
    deps: List[Dict[str, Any]] = field(default_factory=list)
    stmtOrder: List[int] = field(default_factory=list)
    typedRegionTrees: Dict[str, Any] = field(default_factory=dict)

def load_scirpy_facts(analysis_dict: dict) -> ScirpyFactsV2 | None:
    if not analysis_dict:
        return None
    try:
        classes = []
        for c_dict in analysis_dict.get("classes", []):
            c_name = c_dict.get("name") or c_dict.get("className", "")
            methods = []
            for m_dict in c_dict.get("methods", []):
                m_name = m_dict.get("name") or m_dict.get("methodName", "")
                m_summary = m_dict.get("methodSummary")
                m_stmts = m_dict.get("statements", [])
                methods.append(ScirpyMethodFact(
                    name=m_name,
                    methodSummary=m_summary,
                    statements=m_stmts
                ))
            classes.append(ScirpyClassFact(name=c_name, methods=methods))
            
        loops = []
        for l_dict in analysis_dict.get("loops", []):
            queries = []
            for q_dict in l_dict.get("queries", []):
                labels = {str(k): str(v) for k, v in q_dict.get("labels", {}).items()}
                queries.append(ScirpyQueryFact(
                    callLineno=q_dict.get("callLineno", -1),
                    cyclic=q_dict.get("cyclic", False),
                    labels=labels,
                    deps=q_dict.get("deps", []),
                    stmtOrder=q_dict.get("stmtOrder", [])
                ))
            loops.append(ScirpyLoopFact(
                method=l_dict.get("method", ""),
                headLineno=l_dict.get("headLineno", -1),
                testVars=l_dict.get("testVars", []),
                queries=queries,
                stmtOrder=l_dict.get("stmtOrder", []),
                deps=l_dict.get("deps", []),
                cyclic=l_dict.get("cyclic", False) or any(q.cyclic for q in queries)
            ))
            
        return ScirpyFactsV2(
            classes=classes,
            loops=loops,
            deps=analysis_dict.get("deps", []),
            stmtOrder=analysis_dict.get("stmtOrder", []),
            typedRegionTrees=analysis_dict.get("typedRegionTrees", {})
        )
    except Exception:
        return None
