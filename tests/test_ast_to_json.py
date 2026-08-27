"""Tests for AST to JSON conversion."""
from src.ast_to_json import source_to_json
from pathlib import Path

def test_simple_assignment():
    result = source_to_json("x = 1", Path("test.py"))
    assert result["ast_type"] == "Module"
    assert len(result["body"]) == 1

def test_function_def():
    code = "def foo(x):\n    return x + 1"
    result = source_to_json(code, Path("test.py"))
    assert result["body"][0]["ast_type"] == "FunctionDef"
