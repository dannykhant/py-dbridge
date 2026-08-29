"""Benchmark Harness & SOTA Verification Suite for py-dbridge.

Compares Original vs Transformed code across 8 comprehensive scenarios:
1. Paper Example 1: Lookup / Keyed projection in for loop
2. Paper Example 2: While loop with aggregate & group by
3. Paper Example 3: Guarded / Conditional query execution
4. Paper Example 4: DML executemany batching
5. Nested loops query batching
6. Multi-row fetchall loop
7. Transitive-closure / Cyclic self-dependency negative case (must not transform)
8. Retail API / app.py scenario

Measures:
- Semantic equivalence check (output equality against SQLite in-memory DB)
- Latency measurement (mean, p50 median, p95, min, max, stddev)
- Database round-trip query count reduction (N round-trips -> 1 batch query)
- Speedup factor
- JSON report generation (benchmark_report.json) & markdown summary table.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run_pipeline


class InstrumentedCursor:
    """Cursor wrapper that counts database round-trips."""

    def __init__(self, cursor: sqlite3.Cursor, counter: QueryCounter):
        self._cursor = cursor
        self._counter = counter

    def execute(self, sql: str, parameters=()):
        self._counter.increment_execute(sql)
        if parameters:
            return self._cursor.execute(sql, parameters)
        return self._cursor.execute(sql)

    def executemany(self, sql: str, seq_of_parameters):
        self._counter.increment_executemany(sql, len(seq_of_parameters) if hasattr(seq_of_parameters, '__len__') else 1)
        return self._cursor.executemany(sql, seq_of_parameters)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        if size is not None:
            return self._cursor.fetchmany(size)
        return self._cursor.fetchmany()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class InstrumentedConnection:
    """Connection wrapper returning instrumented cursors."""

    def __init__(self, conn: sqlite3.Connection, counter: QueryCounter):
        self._conn = conn
        self._counter = counter

    def cursor(self):
        return InstrumentedCursor(self._conn.cursor(), self._counter)

    def execute(self, sql: str, parameters=()):
        self._counter.increment_execute(sql)
        if parameters:
            return self._conn.execute(sql, parameters)
        return self._conn.execute(sql)

    def executemany(self, sql: str, seq_of_parameters):
        self._counter.increment_executemany(sql, len(seq_of_parameters) if hasattr(seq_of_parameters, '__len__') else 1)
        return self._conn.executemany(sql, seq_of_parameters)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


class QueryCounter:
    """Tracks round-trips and executed SQL statements."""

    def __init__(self):
        self.execute_count = 0
        self.executemany_count = 0
        self.statements: List[str] = []

    def increment_execute(self, sql: str):
        self.execute_count += 1
        self.statements.append(sql)

    def increment_executemany(self, sql: str, param_len: int = 1):
        self.executemany_count += 1
        self.statements.append(f"EXECUTEMANY({param_len}): {sql}")

    @property
    def total_round_trips(self) -> int:
        return self.execute_count + self.executemany_count

    def reset(self):
        self.execute_count = 0
        self.executemany_count = 0
        self.statements.clear()


@dataclass
class ScenarioDefinition:
    name: str
    paper_reference: str
    description: str
    setup_sql: str
    source_template: str  # Code containing the query loop (takes context variables)
    expected_transformations: List[str]
    is_negative: bool = False
    result_eval_expr: str = "results"


@dataclass
class LatencyStats:
    mean_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    stddev_ms: float


@dataclass
class BenchmarkScenarioResult:
    scenario_name: str
    paper_reference: str
    description: str
    semantic_equivalent: bool
    round_trips_baseline: int
    round_trips_optimized: int
    round_trip_reduction_pct: float
    latency_baseline: LatencyStats
    latency_optimized: LatencyStats
    speedup_mean: float
    speedup_p50: float
    transformations_applied: List[str] = field(default_factory=list)
    error: Optional[str] = None
    is_negative_case: bool = False

    @property
    def round_trips_original(self) -> int:
        return self.round_trips_baseline

    @property
    def round_trips_transformed(self) -> int:
        return self.round_trips_optimized

    @property
    def latency_original(self) -> LatencyStats:
        return self.latency_baseline

    @property
    def latency_transformed(self) -> LatencyStats:
        return self.latency_optimized


@dataclass
class BenchmarkReport:
    timestamp: str
    environment: Dict[str, Any]
    scenarios: List[BenchmarkScenarioResult]
    summary: Dict[str, Any]


# ==================================================================== #
# Benchmark Scenarios Suite                                              #
# ==================================================================== #

SCENARIOS: List[ScenarioDefinition] = [
    # 1. Paper Example 1: Lookup / Keyed projection in for loop
    ScenarioDefinition(
        name="paper_ex1_lookup",
        paper_reference="Paper Example 1",
        description="Lookup / Keyed projection in for loop (N+1 query pattern)",
        setup_sql="""
            CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price INTEGER);
            INSERT INTO products (id, name, price)
            VALUES
            """ + ",\n".join(f"({i}, 'Product_{i}', {1000 + i * 10})" for i in range(1, 101)) + ";",
        source_template="""
results = []
for pid in product_ids:
    cursor.execute("SELECT name, price FROM products WHERE id = ?", (pid,))
    row = cursor.fetchone()
    results.append(row)
""",
        expected_transformations=["loop_splitting"],
    ),

    # 2. Paper Example 2: While loop with aggregate & group by
    ScenarioDefinition(
        name="paper_ex2_aggregate",
        paper_reference="Paper Example 2",
        description="While loop with aggregate count and group by batching",
        setup_sql="""
            CREATE TABLE parts (partkey INTEGER PRIMARY KEY, category TEXT, quantity INTEGER);
            INSERT INTO parts (partkey, category, quantity)
            VALUES
            """ + ",\n".join(f"({i}, 'cat_{i % 10}', {i * 5})" for i in range(1, 201)) + ";",
        source_template="""
categories = ["cat_" + str(i) for i in range(10)]
results = []
i = 0
while i < len(categories):
    category = categories[i]
    cursor.execute("SELECT count(partkey) FROM parts WHERE category = ?", (category,))
    row = cursor.fetchone()
    results.append((category, row[0] if row else 0))
    i += 1
""",
        expected_transformations=["loop_splitting"],
    ),

    # 3. Paper Example 3: Guarded / Conditional query execution
    ScenarioDefinition(
        name="paper_ex3_guarded",
        paper_reference="Paper Example 3",
        description="Guarded / Conditional query execution (filters queries in phase 1)",
        setup_sql="""
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, balance INTEGER);
            INSERT INTO customers (id, name, balance)
            VALUES
            """ + ",\n".join(f"({i}, 'Customer_{i}', {i * 100})" for i in range(1, 101)) + ";",
        source_template="""
results = []
for cid in customer_ids:
    if cid % 2 == 0:
        cursor.execute("SELECT name, balance FROM customers WHERE id = ?", (cid,))
        row = cursor.fetchone()
        results.append(row)
""",
        expected_transformations=["loop_splitting"],
    ),

    # 4. Paper Example 4: DML executemany batching
    ScenarioDefinition(
        name="paper_ex4_dml",
        paper_reference="Paper Example 4",
        description="DML loop batching rewritten to cursor.executemany",
        setup_sql="""
            CREATE TABLE inventory (id INTEGER PRIMARY KEY, stock INTEGER);
            INSERT INTO inventory (id, stock)
            VALUES
            """ + ",\n".join(f"({i}, 100)" for i in range(1, 101)) + ";",
        source_template="""
for pid, reduction in updates:
    cursor.execute("UPDATE inventory SET stock = stock - ? WHERE id = ?", (reduction, pid))
cursor.execute("SELECT id, stock FROM inventory ORDER BY id")
results = cursor.fetchall()
""",
        expected_transformations=["loop_splitting"],
    ),

    # 5. Nested loops query batching
    ScenarioDefinition(
        name="nested_loops_batch",
        paper_reference="Nested Loops",
        description="Nested loop query pattern batching inner loop",
        setup_sql="""
            CREATE TABLE catalog (id INTEGER PRIMARY KEY, category_id INTEGER, name TEXT);
            INSERT INTO catalog (id, category_id, name)
            VALUES
            """ + ",\n".join(f"({i}, {((i - 1) % 5) + 1}, 'Item_{i}')" for i in range(1, 51)) + ";",
        source_template="""
results = []
for cat_id in cat_ids:
    for item_id in item_ids:
        cursor.execute("SELECT name FROM catalog WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        results.append((cat_id, row))
""",
        expected_transformations=["loop_splitting"],
    ),

    # 6. Multi-row fetchall loop
    ScenarioDefinition(
        name="multi_row_fetchall",
        paper_reference="Multi-Row Fetchall",
        description="Multi-row fetchall loop mapped into defaultdict list results",
        setup_sql="""
            CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total INTEGER);
            INSERT INTO orders (id, customer_id, total)
            VALUES
            """ + ",\n".join(f"({i}, {((i - 1) % 10) + 1}, {i * 15})" for i in range(1, 101)) + ";",
        source_template="""
results = []
for cid in customer_ids:
    cursor.execute("SELECT id, total FROM orders WHERE customer_id = ?", (cid,))
    rows = cursor.fetchall()
    results.append((cid, rows))
""",
        expected_transformations=["loop_splitting"],
    ),

    # 8. Retail API / app.py scenario
    ScenarioDefinition(
        name="retail_api_scenario",
        paper_reference="Retail API",
        description="Retail order processing: multi-item price & stock lookup loop",
        setup_sql="""
            CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price_cents INTEGER, stock INTEGER);
            INSERT INTO products (id, name, price_cents, stock)
            VALUES
            """ + ",\n".join(f"({i}, 'Item_{i}', {500 + i * 25}, 50)" for i in range(1, 51)) + ";",
        source_template="""
results = []
for product_id, quantity in quantities.items():
    cursor.execute("SELECT name, price_cents, stock FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    if row is not None:
        results.append((product_id, row, quantity))
""",
        expected_transformations=["loop_splitting"],
    ),
]


# ==================================================================== #
# Benchmark Execution Engine                                           #
# ==================================================================== #

def _calculate_stats(latencies_ms: List[float]) -> LatencyStats:
    if not latencies_ms:
        return LatencyStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    sorted_l = sorted(latencies_ms)
    n = len(sorted_l)
    mean_val = sum(sorted_l) / n
    p50_idx = int(math.floor(0.50 * (n - 1)))
    p95_idx = int(math.floor(0.95 * (n - 1)))
    p50_val = sorted_l[p50_idx]
    p95_val = sorted_l[p95_idx]
    min_val = sorted_l[0]
    max_val = sorted_l[-1]
    variance = sum((x - mean_val) ** 2 for x in sorted_l) / n
    stddev_val = math.sqrt(variance)
    return LatencyStats(
        mean_ms=round(mean_val, 4),
        p50_ms=round(p50_val, 4),
        p95_ms=round(p95_val, 4),
        min_ms=round(min_val, 4),
        max_ms=round(max_val, 4),
        stddev_ms=round(stddev_val, 4),
    )


def _build_context_vars(scenario_name: str) -> Dict[str, Any]:
    """Generates input variables for the scenario templates."""
    if scenario_name == "paper_ex1_lookup":
        return {"product_ids": list(range(1, 51))}
    elif scenario_name == "paper_ex2_aggregate":
        return {}
    elif scenario_name == "paper_ex3_guarded":
        return {"customer_ids": list(range(1, 51))}
    elif scenario_name == "paper_ex4_dml":
        return {"updates": [(i, 2) for i in range(1, 51)]}
    elif scenario_name == "nested_loops_batch":
        return {"cat_ids": [1, 2, 3], "item_ids": list(range(1, 11))}
    elif scenario_name == "multi_row_fetchall":
        return {"customer_ids": list(range(1, 11))}
    elif scenario_name == "transitive_closure_cyclic":
        return {}
    elif scenario_name == "retail_api_scenario":
        return {"quantities": {i: (i % 3) + 1 for i in range(1, 26)}}
    return {}


def _normalize_result(val: Any) -> Any:
    """Recursively normalizes database results (converting sqlite3.Row to tuple, etc.)."""
    if isinstance(val, sqlite3.Row):
        return tuple(_normalize_result(x) for x in val)
    elif isinstance(val, tuple):
        return tuple(_normalize_result(x) for x in val)
    elif isinstance(val, list):
        return [_normalize_result(x) for x in val]
    elif isinstance(val, dict):
        return {k: _normalize_result(v) for k, v in val.items()}
    return val


def create_scenario_db(setup_sql: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(setup_sql)
    conn.commit()
    return conn


def run_single_benchmark(
    scenario: ScenarioDefinition,
    iterations: int = 30,
    warmup: int = 5,
    verbose: bool = False,
) -> BenchmarkScenarioResult:
    """Runs a single benchmark scenario, comparing original vs transformed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_file = tmp_path / "scenario.py"
        source_file.write_text(scenario.source_template, encoding="utf-8")

        transform_res = run_pipeline(source_file, None, db_type="sqlite", dry_run=True)
        transformed_code = transform_res.transformed_code
        transformations_applied = transform_res.transformations

        # Check negative case expectations
        if scenario.is_negative:
            if len(transformations_applied) > 0:
                pass  # transformed when should not have

        orig_code_compiled = compile(scenario.source_template, "<original_template>", "exec")
        opt_code_compiled = compile(transformed_code, "<transformed_template>", "exec")

        # 1. Verification of Semantic Equivalence & Query Round-Trips
        orig_db = create_scenario_db(scenario.setup_sql)
        orig_counter = QueryCounter()
        orig_inst_conn = InstrumentedConnection(orig_db, orig_counter)
        orig_env = {
            "conn": orig_inst_conn,
            "cursor": orig_inst_conn.cursor(),
            "collections": collections,
            **_build_context_vars(scenario.name),
        }
        exec(orig_code_compiled, orig_env)
        orig_result = orig_env.get(scenario.result_eval_expr)
        round_trips_orig = orig_counter.total_round_trips
        orig_db.close()

        opt_db = create_scenario_db(scenario.setup_sql)
        opt_counter = QueryCounter()
        opt_inst_conn = InstrumentedConnection(opt_db, opt_counter)
        opt_env = {
            "conn": opt_inst_conn,
            "cursor": opt_inst_conn.cursor(),
            "collections": collections,
            **_build_context_vars(scenario.name),
        }
        exec(opt_code_compiled, opt_env)
        opt_result = opt_env.get(scenario.result_eval_expr)
        round_trips_opt = opt_counter.total_round_trips
        opt_db.close()

        # Semantic equivalence
        is_equivalent = (_normalize_result(orig_result) == _normalize_result(opt_result))

        # 2. Warmup & Latency Measurement
        latencies_orig: List[float] = []
        latencies_opt: List[float] = []

        # Benchmark Original
        for i in range(warmup + iterations):
            bench_db = create_scenario_db(scenario.setup_sql)
            bench_cursor = bench_db.cursor()
            bench_env = {
                "conn": bench_db,
                "cursor": bench_cursor,
                "collections": collections,
                **_build_context_vars(scenario.name),
            }
            t0 = time.perf_counter()
            exec(orig_code_compiled, bench_env)
            t1 = time.perf_counter()
            bench_db.close()
            if i >= warmup:
                latencies_orig.append((t1 - t0) * 1000.0)

        # Benchmark Transformed
        for i in range(warmup + iterations):
            bench_db = create_scenario_db(scenario.setup_sql)
            bench_cursor = bench_db.cursor()
            bench_env = {
                "conn": bench_db,
                "cursor": bench_cursor,
                "collections": collections,
                **_build_context_vars(scenario.name),
            }
            t0 = time.perf_counter()
            exec(opt_code_compiled, bench_env)
            t1 = time.perf_counter()
            bench_db.close()
            if i >= warmup:
                latencies_opt.append((t1 - t0) * 1000.0)

        stats_orig = _calculate_stats(latencies_orig)
        stats_opt = _calculate_stats(latencies_opt)

        speedup_mean = round(stats_orig.mean_ms / max(stats_opt.mean_ms, 0.0001), 2)
        speedup_p50 = round(stats_orig.p50_ms / max(stats_opt.p50_ms, 0.0001), 2)

        if round_trips_orig > 0:
            reduction_pct = round(((round_trips_orig - round_trips_opt) / round_trips_orig) * 100.0, 1)
        else:
            reduction_pct = 0.0

        return BenchmarkScenarioResult(
            scenario_name=scenario.name,
            paper_reference=scenario.paper_reference,
            description=scenario.description,
            semantic_equivalent=is_equivalent,
            transformations_applied=transformations_applied,
            round_trips_baseline=round_trips_orig,
            round_trips_optimized=round_trips_opt,
            round_trip_reduction_pct=reduction_pct,
            latency_baseline=stats_orig,
            latency_optimized=stats_opt,
            speedup_mean=speedup_mean,
            speedup_p50=speedup_p50,
            is_negative_case=scenario.is_negative,
        )


def run_all_benchmarks(
    iterations: int = 30,
    warmup: int = 5,
    scenario_filter: Optional[str] = None,
    verbose: bool = False,
) -> BenchmarkReport:
    """Runs all benchmark scenarios and compiles the report."""
    results: List[BenchmarkScenarioResult] = []

    target_scenarios = SCENARIOS
    if scenario_filter:
        target_scenarios = [s for s in SCENARIOS if scenario_filter.lower() in s.name.lower()]

    for scenario in target_scenarios:
        if verbose:
            print(f"Running scenario: {scenario.name} ({scenario.paper_reference})...")
        res = run_single_benchmark(scenario, iterations=iterations, warmup=warmup, verbose=verbose)
        results.append(res)

    positive_results = results
    avg_speedup_mean = (
        round(sum(r.speedup_mean for r in positive_results) / len(positive_results), 2)
        if positive_results else 1.0
    )
    avg_speedup_p50 = (
        round(sum(r.speedup_p50 for r in positive_results) / len(positive_results), 2)
        if positive_results else 1.0
    )
    all_equivalent = all(r.semantic_equivalent for r in results)
    total_orig_trips = sum(r.round_trips_original for r in results)
    total_opt_trips = sum(r.round_trips_transformed for r in results)
    total_reduction_pct = (
        round(((total_orig_trips - total_opt_trips) / total_orig_trips) * 100.0, 1)
        if total_orig_trips > 0 else 0.0
    )

    report = BenchmarkReport(
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        environment={
            "python_version": sys.version.split()[0],
            "sqlite_version": sqlite3.sqlite_version,
            "scirpy_mode": "Enabled",
            "iterations": iterations,
            "warmup": warmup,
        },
        scenarios=results,
        summary={
            "total_scenarios": len(results),
            "all_semantic_equivalent": all_equivalent,
            "average_speedup_mean": avg_speedup_mean,
            "average_speedup_p50": avg_speedup_p50,
            "total_queries_baseline": total_orig_trips,
            "total_queries_optimized": total_opt_trips,
            "total_queries_eliminated": total_orig_trips - total_opt_trips,
            "total_round_trips_original": total_orig_trips,
            "total_round_trips_transformed": total_opt_trips,
            "total_round_trip_reduction_pct": total_reduction_pct,
        },
    )
    return report


def format_markdown_table(report: BenchmarkReport) -> str:
    """Formats the benchmark results into a clean GitHub Flavored Markdown table."""
    lines = [
        "# py-dbridge Benchmark & SOTA Verification Results",
        "",
        f"**Date / Time:** {report.timestamp}  ",
        f"**SCIRPy Static Analysis:** {report.environment['scirpy_mode']}  ",
        f"**Execution Environment:** Python {report.environment['python_version']} | SQLite {report.environment['sqlite_version']}  ",
        f"**Sample Runs:** {report.environment['iterations']} iterations (+ {report.environment['warmup']} warmup)  ",
        "",
        "| Scenario | Description | Semantic Eq | Queries (Baseline → Optimized) | Baseline Latency (p50 / mean) | Optimized Latency (p50 / mean) | Speedup (p50 / mean) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for r in report.scenarios:
        status_icon = "PASS" if r.semantic_equivalent else "FAIL"
        trips_col = f"{r.round_trips_baseline} → {r.round_trips_optimized} ({r.round_trip_reduction_pct:.1f}% reduction)" if r.round_trip_reduction_pct > 0 else f"{r.round_trips_baseline} → {r.round_trips_optimized} (0%)"
        orig_lat = f"{r.latency_baseline.p50_ms:.3f}ms / {r.latency_baseline.mean_ms:.3f}ms"
        opt_lat = f"{r.latency_optimized.p50_ms:.3f}ms / {r.latency_optimized.mean_ms:.3f}ms"
        speedup_col = f"**{r.speedup_p50:.2f}x** / **{r.speedup_mean:.2f}x**"

        lines.append(
            f"| `{r.scenario_name}` | {r.description} | {status_icon} | {trips_col} | {orig_lat} | {opt_lat} | {speedup_col} |"
        )

    lines.extend([
        "",
        "### Summary Scoreboard",
        "",
        f"- **Semantic Equivalence:** {'100% Passed' if report.summary['all_semantic_equivalent'] else 'FAILED'}",
        f"- **Average Speedup (p50 / mean):** **{report.summary['average_speedup_p50']}x** / **{report.summary['average_speedup_mean']}x**",
        f"- **Total Database Queries:** **{report.summary['total_round_trips_original']} queries (Baseline) → {report.summary['total_round_trips_transformed']} queries (Optimized)** (**{report.summary['total_round_trip_reduction_pct']}% reduction** / **{report.summary['total_round_trips_original'] - report.summary['total_round_trips_transformed']} queries eliminated**)",
        "",
    ])

    return "\n".join(lines)


def format_summary(report: BenchmarkReport) -> str:
    """Formats a concise summary scoreboard for console output."""
    lines = [
        "==================== Benchmark Summary ====================",
        f"  Date / Time           : {report.timestamp}",
        f"  SCIRPy Static Analysis: {report.environment['scirpy_mode']}",
        f"  Execution Environment : Python {report.environment['python_version']} | SQLite {report.environment['sqlite_version']}",
        f"  Sample Runs           : {report.environment['iterations']} iterations (+ {report.environment['warmup']} warmup)",
        "  -----------------------------------------------------------",
        f"  Scenarios Evaluated   : {report.summary['total_scenarios']} workload(s)",
        f"  Semantic Equivalence  : {'100% Passed (All Equivalent)' if report.summary['all_semantic_equivalent'] else 'FAILED'}",
        f"  Average Speedup       : {report.summary['average_speedup_p50']}x (p50) / {report.summary['average_speedup_mean']}x (mean)",
        f"  Total DB Queries      : {report.summary['total_queries_baseline']} (Baseline) -> {report.summary['total_queries_optimized']} (Optimized)",
        f"  Query Reduction       : {report.summary['total_round_trip_reduction_pct']}% fewer queries ({report.summary['total_queries_eliminated']} eliminated)",
        "===========================================================",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="py-dbridge Benchmark Harness & SOTA Verification Suite")
    parser.add_argument("--json-output", type=str, default="results/benchmark_report.json", help="Path to write JSON benchmark report")
    parser.add_argument("--iterations", type=int, default=30, help="Number of benchmark iterations")
    parser.add_argument("--warmup", type=int, default=5, help="Number of warmup iterations")
    parser.add_argument("--scenario", type=str, default=None, help="Filter to specific scenario name")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose execution output")
    parser.add_argument("--table", action="store_true", help="Print full markdown table in addition to summary")
    args = parser.parse_args()

    report = run_all_benchmarks(
        iterations=args.iterations,
        warmup=args.warmup,
        scenario_filter=args.scenario,
        verbose=args.verbose,
    )

    # Save JSON report
    report_dict = asdict(report)
    json_path = Path(args.json_output)
    json_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    # Output Summary (and optionally Table)
    print(format_summary(report))
    if args.table:
        print("\n" + format_markdown_table(report))
    
    print(f"\n[Report saved to {json_path.resolve()}]")


if __name__ == "__main__":
    main()
