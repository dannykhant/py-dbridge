"""Tests for the benchmark harness and SOTA verification suite."""
import json
from pathlib import Path
import pytest
from benchmarks.run_benchmark import (
    SCENARIOS,
    run_single_benchmark,
    run_all_benchmarks,
    format_markdown_table,
    BenchmarkReport,
)

@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_benchmark_scenario_semantic_equivalence(scenario):
    """Verify each benchmark scenario preserves exact semantic equivalence."""
    result = run_single_benchmark(scenario, iterations=5, warmup=2)
    assert result.semantic_equivalent is True, f"Scenario {scenario.name} produced mismatched output!"


def test_round_trip_reduction_on_transformable_scenarios():
    """Verify that transformable scenarios achieve significant DB round-trip reductions."""
    for scenario in SCENARIOS:
        if not scenario.is_negative:
            result = run_single_benchmark(scenario, iterations=3, warmup=1)
            assert result.round_trips_transformed < result.round_trips_original, (
                f"Expected round trip reduction for {scenario.name}: "
                f"{result.round_trips_original} -> {result.round_trips_transformed}"
            )
            assert result.round_trip_reduction_pct > 0.0


def test_cyclic_negative_scenario_not_transformed():
    """Verify that cyclic transitive closure scenario is not modified (0 transformations)."""
    cyclic_scenario = next(s for s in SCENARIOS if s.name == "transitive_closure_cyclic")
    result = run_single_benchmark(cyclic_scenario, iterations=3, warmup=1)
    assert result.is_negative_case is True
    assert len(result.transformations_applied) == 0
    assert result.round_trips_transformed == result.round_trips_original
    assert result.semantic_equivalent is True


def test_run_all_benchmarks_and_report_generation(tmp_path):
    """Verify that run_all_benchmarks generates a complete, valid report."""
    report = run_all_benchmarks(iterations=5, warmup=2)
    assert isinstance(report, BenchmarkReport)
    assert len(report.scenarios) == len(SCENARIOS)
    assert report.summary["all_semantic_equivalent"] is True
    assert report.summary["average_speedup_mean"] >= 1.0

    # Test markdown formatting
    md = format_markdown_table(report)
    assert "# py-dbridge Benchmark & SOTA Verification Results" in md
    assert "Summary Scoreboard" in md

    # Test JSON serialization
    json_path = tmp_path / "benchmark_report.json"
    from dataclasses import asdict
    json_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["summary"]["total_scenarios"] == len(SCENARIOS)


def test_conditional_else_branch_benchmark_scenario():
    """Verify guarded loop with else-branch preserves semantic equivalence and reduces round trips."""
    from benchmarks.run_benchmark import ScenarioDefinition
    scenario = ScenarioDefinition(
        name="guarded_with_else_branch",
        paper_reference="Paper Example 3 Extended",
        description="Guarded loop with else branch and trailing statements",
        setup_sql="""
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
            INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Charlie'), (4, 'Dave');
        """,
        source_template="""
uids = [1, 2, 3, 4]
results = []
for uid in uids:
    if uid % 2 == 0:
        cursor.execute("SELECT name FROM users WHERE id = ?", (uid,))
        row = cursor.fetchone()
        results.append(row[0] if row else None)
    else:
        results.append("ODD")
""",
        expected_transformations=["loop_splitting"],
    )
    result = run_single_benchmark(scenario, iterations=3, warmup=1)
    assert result.semantic_equivalent is True
    assert result.round_trips_transformed < result.round_trips_original


def test_dml_rowcount_benchmark_scenario_negative():
    """Verify DML with rowcount dependency is not transformed (negative case)."""
    from benchmarks.run_benchmark import ScenarioDefinition
    scenario = ScenarioDefinition(
        name="dml_rowcount_negative",
        paper_reference="DML Dependency Rule",
        description="DML loop with rowcount check cannot be batched",
        setup_sql="""
            CREATE TABLE inventory (id INTEGER PRIMARY KEY, stock INTEGER);
            INSERT INTO inventory (id, stock) VALUES (1, 10), (2, 20);
        """,
        source_template="""
pids = [1, 2]
results = []
for pid in pids:
    cursor.execute("UPDATE inventory SET stock = stock - 1 WHERE id = ?", (pid,))
    results.append(cursor.rowcount)
""",
        expected_transformations=[],
        is_negative=True,
    )
    result = run_single_benchmark(scenario, iterations=3, warmup=1)
    assert result.is_negative_case is True
    assert len(result.transformations_applied) == 0
    assert result.semantic_equivalent is True


def test_per_query_self_cyclic_behavior():
    """Verify a loop where query is cyclic carried dependency is not transformed."""
    from benchmarks.run_benchmark import ScenarioDefinition
    scenario = ScenarioDefinition(
        name="per_query_cyclic_behavior",
        paper_reference="Self-cyclic Rule",
        description="Loop with cyclic query carried dependency",
        setup_sql="""
            CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER);
            INSERT INTO nodes (id, parent_id) VALUES (1, 2), (2, 3), (3, NULL);
        """,
        source_template="""
curr = 1
results = []
while curr is not None:
    cursor.execute("SELECT parent_id FROM nodes WHERE id = ?", (curr,))
    row = cursor.fetchone()
    if row and row[0] is not None:
        curr = row[0]
        results.append(curr)
    else:
        curr = None
""",
        expected_transformations=[],
        is_negative=True,
    )
    result = run_single_benchmark(scenario, iterations=3, warmup=1)
    assert result.is_negative_case is True
    assert len(result.transformations_applied) == 0
    assert result.semantic_equivalent is True

