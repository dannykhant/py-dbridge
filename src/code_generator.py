"""Generate Python source code from transformed AST.

Uses ast.unparse() (Python 3.9+) for code generation.
"""
import ast

def generate_code(transformed_ir) -> str:
    """Generate Python source from transformed IR."""
    return ast.unparse(transformed_ir.transformed_ast)
