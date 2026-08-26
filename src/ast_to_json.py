"""Convert Python source to JSON AST representation."""
import ast
import json
import sys
from pathlib import Path

src_path = str(Path(__file__).resolve().parents[1] / "scirpy")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

def source_to_json(source_code: str, source_path: Path) -> dict:
    """Parse Python source into AST and serialize to JSON dict."""
    tree = ast.parse(source_code, filename=str(source_path))
    return ast_to_dict(tree)

def ast_to_dict(tree: ast.AST) -> dict:
    """Convert AST to dictionary (reuses existing astexport logic)."""
    from astexport.export import export_dict
    return export_dict(tree)
