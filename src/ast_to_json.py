"""Convert Python source to JSON AST representation."""
import ast
import copy
import json
from pathlib import Path

class JoinedStrTransformer(ast.NodeTransformer):
    """Normalize JoinedStr (f-strings) to BinOp(+) calls so Java SCIRPy parser can handle them."""
    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        self.generic_visit(node)
        if not node.values:
            return ast.Constant(value="")
        parts = []
        for val in node.values:
            if isinstance(val, ast.FormattedValue):
                parts.append(ast.Call(
                    func=ast.Name(id="str", ctx=ast.Load()),
                    args=[val.value],
                    keywords=[]
                ))
            else:
                parts.append(val)
        res = parts[0]
        for p in parts[1:]:
            res = ast.BinOp(left=res, op=ast.Add(), right=p)
        return ast.copy_location(res, node)

class IfExpTransformer(ast.NodeTransformer):
    """Normalize IfExp so Java SCIRPy parser can extract data flow without crashing."""
    def visit_IfExp(self, node: ast.IfExp) -> ast.AST:
        self.generic_visit(node)
        res = ast.Call(
            func=ast.Name(id="_pyd_ifexp", ctx=ast.Load()),
            args=[node.test, node.body, node.orelse],
            keywords=[]
        )
        return ast.copy_location(res, node)

def source_to_json(source_code: str, source_path: Path) -> dict:
    """Parse Python source into AST and serialize to JSON dict."""
    tree = ast.parse(source_code, filename=str(source_path))
    return ast_to_dict(tree)

def ast_to_dict(tree: ast.AST) -> dict:
    """Convert AST to dictionary (reuses existing astexport logic)."""
    from src.astexport.export import export_dict
    normalized_tree = JoinedStrTransformer().visit(copy.deepcopy(tree))
    normalized_tree = IfExpTransformer().visit(normalized_tree)
    ast.fix_missing_locations(normalized_tree)
    return export_dict(normalized_tree)
