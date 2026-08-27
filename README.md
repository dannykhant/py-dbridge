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
