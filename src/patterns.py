"""Detect database query patterns in Python AST.

Identifies:
- cursor.execute() calls inside loops (for/while)
- Parameter bindings (%(name)s or %s style)
- Data dependencies between loop variables and query parameters
"""
import ast
from dataclasses import dataclass, field
from pathlib import Path


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _parent_dir(path: str) -> Path:
    return Path(path).resolve().parent


def _resolve_module_file(mod: str, source_dir: str) -> str | None:
    """Best-effort: locate a module's .py file on disk.

    Searches the source directory and walks up its ancestors (mirroring the
    `sys.path.insert` trick used by drivers that load sibling config modules).
    """
    leaf = mod.replace(".", "/")
    base = Path(source_dir).resolve()
    for dir_ in [base, *base.parents]:
        direct = dir_ / (leaf + ".py")
        if direct.exists():
            return str(direct)
        pkg = dir_ / leaf / "__init__.py"
        if pkg.exists():
            return str(pkg)
    return None


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

    def __init__(self, source_path: str | None = None):
        self.queries_in_loops: list[QueryInLoop] = []
        self._loop_stack: list[ast.AST] = []
        # Resolved string constant values (module-level + imported), used to
        # turn f-string queries into static SQL so they can be rewritten.
        self._constants: dict[str, str] = {}
        if source_path is not None:
            self._constants = self._collect_constants(ast.parse(
                _read_text(source_path)), source_dir=str(_parent_dir(source_path)))

    def detect(self, tree: ast.AST) -> list[QueryInLoop]:
        # Always resolve module-level string constants from the analyzed tree
        # so same-file `NAME = "value"` interpolations become static SQL.
        self._constants.update(self._collect_constants(tree, source_dir=""))
        self.visit(tree)
        return self.queries_in_loops

    def _collect_constants(self, tree: ast.AST, source_dir: str) -> dict[str, str]:
        """Collect module-level string-constant assignments and imported ones.

        Handles `NAME = "value"` and `from mod import NAME` / `import mod` where
        `mod` is a sibling .py file whose own top-level constants we read.
        """
        consts: dict[str, str] = {}
        imported_modules: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant) \
                            and isinstance(node.value.value, str):
                        consts[t.id] = node.value.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str) and isinstance(node.target, ast.Name):
                consts[node.target.id] = node.value.value
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                imported_modules.append(mod)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.append(alias.name)
        for mod in imported_modules:
            path = _resolve_module_file(mod, source_dir)
            if path is None:
                continue
            try:
                sub = ast.parse(_read_text(path))
                consts.update(self._collect_constants(sub, str(_parent_dir(path))))
            except (OSError, SyntaxError):
                continue
        return consts

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
        fstring_vars: list[str] = []
        fully_resolved = True
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            query_str = first_arg.value
        elif isinstance(first_arg, ast.Name):
            # We don't statically know the query, but we know it's a variable reference
            query_str = f"VAR:{first_arg.id}"
        elif isinstance(first_arg, ast.JoinedStr):
            # F-string query: resolve constants so we get a static SQL string.
            # Interpolations that can't be statically resolved (e.g. a loop
            # variable like `table`) make the query non-batchable -> not
            # transformable, so the original f-string loop is left intact.
            query_str, fstring_vars, fully_resolved = self._resolve_joined_str(first_arg)
        else:
            return None

        if not query_str:
            return None

        # Extract parameters
        parameter_vars = []
        if len(node.args) > 1:
            second_arg = node.args[1]
            parameter_vars = self._find_name_nodes(second_arg)
        # Interpolated f-string identifiers are also query parameters (N+1 over them).
        parameter_vars = list(set(parameter_vars + fstring_vars))

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
        if not fully_resolved:
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

    def _resolve_joined_str(self, node: ast.JoinedStr) -> tuple[str, list[str], bool]:
        """Resolve an f-string query into (static_sql, interpolated_names, fully_resolved).

        Constant parts and statically-known constants (module-level + imported) are
        substituted into the SQL text. Any interpolation that cannot be resolved to a
        literal (e.g. a loop variable such as `table`) is left as-is and flips
        `fully_resolved` to False, marking the query as non-transformable.
        """
        parts: list[str] = []
        names: list[str] = []
        fully_resolved = True
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                expr = value.value
                resolved = self._try_resolve_constant(expr)
                if resolved is not None:
                    parts.append(str(resolved))
                else:
                    fully_resolved = False
                    parts.append("{" + ast.unparse(expr) + "}")
                names.extend(self._find_name_nodes(expr))
        return "".join(parts), list(set(names)), fully_resolved

    def _try_resolve_constant(self, node: ast.AST) -> str | None:
        """Best-effort: resolve a node to a static string constant value."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self._constants.get(node.id)
        return None

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
