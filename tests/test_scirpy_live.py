"""Live integration tests with the Java SCIRPy gateway."""
import pytest
from pathlib import Path

from src.analyzer import run_analysis
from src.scirpy_bridge import _get_gateway


def _is_jvm_available() -> bool:
    try:
        gw, _ = _get_gateway()
        gw.jvm.System.currentTimeMillis()
        return True
    except Exception:
        return False


jvm_required = pytest.mark.skipif(
    not _is_jvm_available(),
    reason="Live Java SCIRPy gateway is not running or unavailable",
)


@jvm_required
def test_scirpy_live_real_loop_non_cyclic(tmp_path: Path):
    """Test 1: Run run_analysis on a real non-cyclic loop.
    
    Verifies that analysis.scirpy_facts.loops is non-empty, queries have
    EXEC/POST labels, PDG deps are present, and cyclic is False.
    """
    code = """
category = 10
while category != -1:
    cursor.execute("SELECT name FROM parts WHERE id = %s", (category,))
    row = cursor.fetchone()
    category = get_parent(category)
"""
    source_file = tmp_path / "test_non_cyclic.py"
    source_file.write_text(code, encoding="utf-8")

    analysis = run_analysis({}, source_file)

    assert analysis.scirpy_facts is not None, "Expected scirpy_facts to be present"
    assert len(analysis.scirpy_facts.loops) > 0, "Expected at least one loop in scirpy_facts.loops"

    loop = analysis.scirpy_facts.loops[0]
    assert len(loop.queries) > 0, "Expected queries in loop"

    query_fact = loop.queries[0]
    # Check that labels contain EXEC and POST
    labels_values = list(query_fact.labels.values()) + list(analysis.labels.values())
    assert any("EXEC" in lbl for lbl in labels_values), "Expected EXEC label in query labels"
    assert any("POST" in lbl for lbl in labels_values), "Expected POST label in query labels"

    # Check PDG deps are present
    assert (
        len(analysis.deps) > 0
        or len(analysis.dependencies) > 0
        or len(loop.deps) > 0
        or len(query_fact.deps) > 0
    ), "Expected PDG deps to be present"

    # Check non-cyclic
    assert query_fact.cyclic is False, "Expected query cyclic to be False"
    assert analysis.cyclic is False, "Expected analysis.cyclic to be False"


@jvm_required
def test_scirpy_live_synthetic_self_cyclic(tmp_path: Path):
    """Test 2: Run run_analysis on a synthetic self-cyclic while-loop.
    
    Verifies that SCIRPy marks cyclic is True, analysis.cyclic is True,
    and len(analysis.transformable_queries) == 0.
    """
    code = """
node = 1
while node:
    cursor.execute("SELECT parent FROM nodes WHERE id = %s", (node,))
    row = cursor.fetchone()
    node = row[0]
"""
    source_file = tmp_path / "test_cyclic.py"
    source_file.write_text(code, encoding="utf-8")

    analysis = run_analysis({}, source_file)

    assert analysis.scirpy_facts is not None, "Expected scirpy_facts to be present"
    assert len(analysis.scirpy_facts.loops) > 0, "Expected at least one loop in scirpy_facts.loops"

    loop = analysis.scirpy_facts.loops[0]
    assert len(loop.queries) > 0, "Expected queries in loop"

    query_fact = loop.queries[0]
    assert query_fact.cyclic is True, "Expected SCIRPy to mark query_fact.cyclic as True"
    assert analysis.cyclic is True, "Expected analysis.cyclic to be True"
    assert len(analysis.transformable_queries) == 0, "Expected 0 transformable queries for cyclic loop"

