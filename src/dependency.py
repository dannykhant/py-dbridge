"""Inter-statement data dependency analysis.

Builds a dependency graph for statements within a loop body,
identifying which statements can be reordered to enable loop splitting.
"""
import ast
import re
from dataclasses import dataclass

@dataclass
class Dependency:
    """A data dependency between two statements."""
    source_index: int      # Statement index that defines/uses a variable
    target_index: int      # Statement index that uses/defines the variable
    variable: str          # The variable creating the dependency
    dep_type: str          # "flow" (RAW), "anti" (WAR), "output" (WAW), "loop_carried"

class DependencyAnalyzer:
    """Analyze data dependencies between statements in a loop body."""

    def analyze_loop(self, loop_node: ast.AST) -> list[Dependency]:
        """Compute dependencies within a loop body."""
        body = loop_node.body
        n = len(body)

        stmt_defs = [self._get_defs(s) for s in body]
        stmt_uses = [self._get_uses(s) for s in body]

        dependencies = []

        for i in range(n):
            for j in range(i + 1, n):
                for var in stmt_defs[i]:
                    if var in stmt_uses[j]:
                        dependencies.append(Dependency(i, j, var, "flow"))
                for var in stmt_uses[i]:
                    if var in stmt_defs[j]:
                        dependencies.append(Dependency(i, j, var, "anti"))
                for var in stmt_defs[i]:
                    if var in stmt_defs[j]:
                        dependencies.append(Dependency(i, j, var, "output"))

        # Loop-carried
        for i in range(n):
            for j in range(n):
                for var in stmt_defs[j]:
                    if var in stmt_uses[i]:
                        dependencies.append(Dependency(j, i, var, "loop_carried"))

        return dependencies

    def classify_loop_stmts(
        self,
        body: list[ast.AST],
        execute_node: ast.Call,
        condition_vars: set[str] = None,
        stmt_facts: dict = None,
        scirpy_facts = None,
    ) -> list[str]:
        """Classify each top-level statement in the loop body.

        Returns one label per statement:
          EXEC     - is or contains the execute call
          ADVANCE  - assigns to a while-condition variable (only when condition_vars given)
          POST     - uses or defines a variable transitively defined by a fetch call
          PRE      - everything else (safe to run in Phase 1)
        """
        if scirpy_facts and hasattr(scirpy_facts, 'loops'):
            exec_lineno = getattr(execute_node, 'lineno', -1)
            found_q = None
            for loop in scirpy_facts.loops:
                for q in loop.queries:
                    if q.callLineno == exec_lineno:
                        found_q = (loop, q)
                        break
                if found_q:
                    break
            if not found_q:
                for stmt in body:
                    if any(child is execute_node for child in ast.walk(stmt)) or stmt is execute_node:
                        stmt_lineno = getattr(stmt, 'lineno', -1)
                        for loop in scirpy_facts.loops:
                            for q in loop.queries:
                                if q.callLineno == stmt_lineno:
                                    exec_lineno = stmt_lineno
                                    found_q = (loop, q)
                                    break
                            if found_q:
                                break
                    if found_q:
                        break

            if found_q:
                loop, q = found_q
                result = []
                post_vars = None
                all_deps = getattr(q, 'deps', []) or getattr(loop, 'deps', []) or getattr(scirpy_facts, 'deps', [])
                for stmt in body:
                    lineno_int = getattr(stmt, 'lineno', -1)
                    lineno_str = str(lineno_int)
                    if post_vars is None:
                        post_vars = self._find_post_vars(body, execute_node, stmt_facts=stmt_facts)
                    
                    label = q.labels.get(lineno_str) or q.labels.get(lineno_int)
                    if label:
                        if label == "PRE" and (self._is_fetch_stmt(stmt) or (self._get_uses(stmt, stmt_facts=stmt_facts) & post_vars) or (self._get_defs(stmt, stmt_facts=stmt_facts) & post_vars)):
                            result.append("POST")
                        else:
                            result.append(label)
                    else:
                        if any(child is execute_node for child in ast.walk(stmt)):
                            result.append("EXEC")
                        elif condition_vars and (self._get_defs(stmt, stmt_facts=stmt_facts) & condition_vars):
                            result.append("ADVANCE")
                        else:
                            is_post_from_deps = False
                            for dep in all_deps:
                                if isinstance(dep, dict):
                                    tgt = dep.get("target") or dep.get("dst") or dep.get("target_index")
                                    src = dep.get("source") or dep.get("src") or dep.get("source_index")
                                    if (tgt == lineno_int or tgt == lineno_str) and (src == exec_lineno or src == str(exec_lineno)):
                                        is_post_from_deps = True
                                        break
                            if is_post_from_deps or self._is_fetch_stmt(stmt) or (self._get_uses(stmt, stmt_facts=stmt_facts) & post_vars) or (self._get_defs(stmt, stmt_facts=stmt_facts) & post_vars):
                                result.append("POST")
                            else:
                                result.append("PRE")
                return result

        post_vars = self._find_post_vars(body, execute_node, stmt_facts=stmt_facts)

        result = []
        for stmt in body:
            if any(child is execute_node for child in ast.walk(stmt)):
                result.append("EXEC")
            elif condition_vars and (self._get_defs(stmt, stmt_facts=stmt_facts) & condition_vars):
                result.append("ADVANCE")
            elif self._is_fetch_stmt(stmt) or (self._get_uses(stmt, stmt_facts=stmt_facts) & post_vars) or (self._get_defs(stmt, stmt_facts=stmt_facts) & post_vars):
                result.append("POST")
            else:
                result.append("PRE")
        return result

    def _is_fetch_stmt(self, stmt: ast.AST) -> bool:
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"fetchone", "fetchall", "fetchmany"}):
                return True
        return False

    def _find_post_vars(self, body: list[ast.AST], execute_node: ast.Call = None, stmt_facts: dict = None) -> set[str]:
        """Find all variables transitively defined by fetch calls."""
        post_vars: set[str] = set()
        
        target_cursor = None
        if execute_node and isinstance(execute_node.func, ast.Attribute):
            target_cursor_node = execute_node.func.value
            if isinstance(target_cursor_node, ast.Name):
                target_cursor = target_cursor_node.id

        # Seed: variables directly assigned from fetch calls
        for stmt in body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Assign):
                    if (isinstance(node.value, ast.Call)
                            and isinstance(node.value.func, ast.Attribute)
                            and node.value.func.attr in {"fetchone", "fetchall", "fetchmany"}):
                        
                        is_target_cursor = True
                        if target_cursor and isinstance(node.value.func.value, ast.Name):
                            if node.value.func.value.id != target_cursor:
                                is_target_cursor = False
                                
                        if is_target_cursor:
                            for t in node.targets:
                                post_vars.update(self._get_names_in_target(t))

        # Transitive closure
        changed = True
        while changed:
            changed = False
            for stmt in body:
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Assign):
                        uses = {n.id for n in ast.walk(node.value)
                                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                        if uses & post_vars:
                            new = set()
                            for t in node.targets:
                                new.update(self._get_names_in_target(t))
                            if not new.issubset(post_vars):
                                post_vars |= new
                                changed = True
        return post_vars

    def has_cyclic_dependency(
        self,
        execute_node: ast.Call,
        body: list[ast.AST],
        param_vars: list[str],
        stmt_facts: dict = None,
        scirpy_facts = None,
    ) -> bool:
        """Return True if param_vars are (transitively) defined from a fetch result.

        Per DBridge paper: a query is not transformable iff its parameter has a
        cyclic data dependency on the query's own result.
        """
        post_vars = self._find_post_vars(body, execute_node, stmt_facts=stmt_facts)
        py_cyclic = bool(set(param_vars) & post_vars)

        if scirpy_facts and hasattr(scirpy_facts, 'loops'):
            exec_lineno = getattr(execute_node, 'lineno', -1)
            found_q = None
            for loop in scirpy_facts.loops:
                for q in loop.queries:
                    if q.callLineno == exec_lineno:
                        found_q = (loop, q)
                        break
                if found_q:
                    break
            if not found_q:
                for stmt in body:
                    if any(child is execute_node for child in ast.walk(stmt)) or stmt is execute_node:
                        stmt_lineno = getattr(stmt, 'lineno', -1)
                        for loop in scirpy_facts.loops:
                            for q in loop.queries:
                                if q.callLineno == stmt_lineno:
                                    exec_lineno = stmt_lineno
                                    found_q = (loop, q)
                                    break
                            if found_q:
                                break
                    if found_q:
                        break

            if found_q:
                loop, q = found_q
                return bool(q.cyclic or py_cyclic)

        return py_cyclic

    def _get_defs(self, node: ast.AST, stmt_facts: dict = None) -> set[str]:
        if stmt_facts and hasattr(node, 'lineno') and node.lineno in stmt_facts:
            facts_defs = set()
            for d in stmt_facts[node.lineno].defs:
                facts_defs.update(re.findall(r'[a-zA-Z_]\w*', d))
            return facts_defs
        defs = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    defs.update(self._get_names_in_target(target))
            elif isinstance(child, ast.AnnAssign):
                defs.update(self._get_names_in_target(child.target))
            elif isinstance(child, ast.AugAssign):
                defs.update(self._get_names_in_target(child.target))
        return defs

    def _get_names_in_target(self, target: ast.AST) -> set[str]:
        names = set()
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                names.update(self._get_names_in_target(elt))
        return names

    def _get_uses(self, node: ast.AST, stmt_facts: dict = None) -> set[str]:
        if stmt_facts and hasattr(node, 'lineno') and node.lineno in stmt_facts:
            facts_uses = set()
            for u in stmt_facts[node.lineno].uses:
                facts_uses.update(re.findall(r'[a-zA-Z_]\w*', u))
            return facts_uses
        return {child.id for child in ast.walk(node)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)}
