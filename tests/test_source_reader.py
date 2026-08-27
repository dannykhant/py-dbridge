"""Tests for source file reading."""
import pytest
from pathlib import Path
from src.source_reader import read_source

def test_read_valid_python_file(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert read_source(f) == "x = 1\n"

def test_read_nonexistent_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_source(tmp_path / "missing.py")

def test_read_non_python_file(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("not python", encoding="utf-8")
    with pytest.raises(ValueError):
        read_source(f)
