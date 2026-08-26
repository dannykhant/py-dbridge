"""Detect database query patterns in Python AST.

Identifies:
- cursor.execute() calls inside loops (for/while)
- Parameter bindings (%(name)s or %s style)
- Data dependencies between loop variables and query parameters
"""
import ast
from dataclasses import dataclass, field

@dataclass
class QueryInLoop:
    """A query execution statement found inside a loop."""
    loop_node: ast.AST            # The for/while loop
    execute_node: ast.Call        # The cursor.execute() call
    query_string: str             # The SQL query text (if statically determinable)
    parameter_vars: list[str]     # Variables used as query parameters
    loop_var: str | None          # The loop iteration variable
    line_number: int              # Line number in source
    has_result_dependency: bool   # Does later code in loop depend on query result?
    is_transformable: bool = True # Can this be transformed to set-oriented?
    is_dml: bool = False

class QueryPatternDetector(ast.NodeVisitor):
    """Walk AST to find query execution patterns inside loops."""

    DB_EXECUTE_METHODS = {"execute", "executemany"}

    def __init__(self):
        self.queries_in_loops: list[QueryInLoop] = []
        self._loop_stack: list[ast.AST] = []

    def detect(self, tree: ast.AST) -> list[QueryInLoop]:
        self.visit(tree)
        return self.queries_in_loops

    def visit_For(self, node: ast.For):
        self._loop_stack.append(node)
        self.generic_visit(node)
        self._loop_stack.pop()

    def visit_While(self, node: ast.While):
        self._loop_stack.append(node)
        self.generic_visit(node)
        self._loop_stack.pop()

    def visit_Call(self, node: ast.Call):
        if self._loop_stack and self._is_db_execute(node):
            query_info = self._extract_query_info(node)
            if query_info:
                self.queries_in_loops.append(query_info)
        self.generic_visit(node)

    def _is_db_execute(self, node: ast.Call) -> bool:
        """Check if this is a cursor.execute() or connection.execute() call."""
        if isinstance(node.func, ast.Attribute):
            return node.func.attr in self.DB_EXECUTE_METHODS
        return False

    def _extract_query_info(self, node: ast.Call) -> QueryInLoop | None:
        """Extract query information from an execute call."""
        if not node.args:
            return None

        # Determine SQL query string if it is a constant string
        query_str = ""
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            query_str = first_arg.value
        elif isinstance(first_arg, ast.Name):
            # We don't statically know the query, but we know it's a variable reference
            query_str = f"VAR:{first_arg.id}"
        else:
            return None

        if not query_str:
            return None

        # Extract parameters
        parameter_vars = []
        if len(node.args) > 1:
            second_arg = node.args[1]
            parameter_vars = self._find_name_nodes(second_arg)

        # Find closest loop variable
        loop_node = self._loop_stack[-1]
        loop_var = None
        if isinstance(loop_node, ast.For):
            # e.g., in `for pid in product_ids:`, target is Name(id='pid')
            if isinstance(loop_node.target, ast.Name):
                loop_var = loop_node.target.id
            elif isinstance(loop_node.target, (ast.Tuple, ast.List)):
                # Handle unpacked loop vars e.g., for k, v in dict.items():
                loop_var = [n.id for n in loop_node.target.elts if isinstance(n, ast.Name)]

        # Check if query results are used in loop
        has_res_dep = self._check_result_dependency(loop_node, node)
        
        is_dml = query_str.strip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        
        is_transformable = True
        if query_str.startswith("VAR:"):
            is_transformable = False
        if is_dml and has_res_dep:
            is_transformable = False

        return QueryInLoop(
            loop_node=loop_node,
            execute_node=node,
            query_string=query_str,
            parameter_vars=parameter_vars,
            loop_var=loop_var,
            line_number=node.lineno,
            has_result_dependency=has_res_dep,
            is_transformable=is_transformable,
            is_dml=is_dml
        )

    def _find_name_nodes(self, node: ast.AST) -> list[str]:
        """Recursively find all Name nodes under an AST node to extract variable names."""
        names = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.append(child.id)
        return list(set(names))

    def _iter_in_order(self, node: ast.AST):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        yield item
                        yield from self._iter_in_order(item)
            elif isinstance(value, ast.AST):
                yield value
                yield from self._iter_in_order(value)

    def _has_result_dependency(self, loop_node: ast.AST, execute_node: ast.Call) -> bool:
        """Check if any statement in loop_node after execute_node depends on its result.
        In Python, this typically means cursor.fetchone(), cursor.fetchall(), cursor.rowcount,
        cursor.lastrowid, or using the cursor as an iterator.
        """
        found_execute = False
        for node in self._iter_in_order(loop_node):
            if node is execute_node:
                found_execute = True
                continue
            if not found_execute:
                continue
            
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"fetchone", "fetchall", "fetchmany"}:
                    return True
            if isinstance(node, ast.Attribute) and node.attr in {"lastrowid", "rowcount"}:
                return True
        return False

    _check_result_dependency = _has_result_dependency
