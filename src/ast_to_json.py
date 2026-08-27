"""Convert Python source to JSON AST representation."""
import ast
import json
from pathlib import Path

def source_to_json(source_code: str, source_path: Path) -> dict:
    """Parse Python source into AST and serialize to JSON dict."""
    tree = ast.parse(source_code, filename=str(source_path))
    return ast_to_dict(tree)

def ast_to_dict(tree: ast.AST) -> dict:
    """Convert AST to dictionary (reuses existing astexport logic)."""
    from src.astexport.export import export_dict
    return export_dict(tree)
