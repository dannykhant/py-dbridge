# py-dbridge (pyd)

Python database application query rewriter for set-oriented batch execution.

## Setup

```bash
uv sync --all-extras
```

## CLI Usage

```bash
# Transform a file
uv run python -m src.cli <source_file.py> -o <output_file.py> --db <postgres|sqlite>

# Show changes without writing to file
uv run python -m src.cli <source_file.py> --dry-run
```

## Run Tests

```bash
uv run pytest
```

## Run Benchmarks

```bash
# Run all benchmark scenarios
uv run python -m benchmarks.run_benchmark

# Run a specific benchmark scenario
uv run python -m benchmarks.run_benchmark --scenario paper_ex1_lookup

# Run with custom iterations and warmup runs
uv run python -m benchmarks.run_benchmark --iterations 50 --warmup 10

# Save JSON report to a custom path
uv run python -m benchmarks.run_benchmark --json-output results/benchmark_report.json
```

