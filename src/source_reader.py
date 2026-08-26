"""Read and validate Python source files."""
from pathlib import Path

def read_source(source: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source}")
    if source.suffix != ".py":
        raise ValueError(f"Expected .py file, got: {source.suffix}")
    return source.read_text(encoding="utf-8")
