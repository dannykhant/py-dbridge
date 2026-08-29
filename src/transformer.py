"""Transformation engine implementing DBridge rules for Python.

Transformation rules (from the DBridge paper):
1. Statement Reordering  - classify stmts so PRE goes before execute
2. Loop Splitting        - split loop: Phase 1 collects params, Phase 2 processes results
3. Query Rewrite         - rewrite SQL to set-oriented form (ANY / IN)
4. Conditional Handling  - preserve if-guards around the execute in both phases
5. While Loop Support    - save/restore condition var, split into two while loops
"""
import ast
import collections
import re
from typing import Any
from dataclasses import dataclass, field
from src.analyzer import AnalysisResult
from src.patterns import QueryInLoop
from src.query_rewriter import QueryRewriter
from src.dependency import DependencyAnalyzer

@dataclass
class TransformedIR:
    original_ast: ast.AST
    transformed_ast: ast.AST
    applied_rules: list[str] = field(default_factory=list)


@dataclass
class QueryTransformContext:
    query: QueryInLoop
    tid: int
    params_name: str
    result_map_name: str
    iter_name: str
    loop_var: str
    param_col: str
    bound_vars: ast.AST


class Phase2MultiTransformer(ast.NodeTransformer):
    """Transformer for the second phase (result processing loop body) supporting multiple queries."""
    def __init__(self, query_contexts: list[QueryTransformContext]):
        self.query_contexts = query_contexts
        self.current_qc: QueryTransformContext | None = query_contexts[0] if len(query_contexts) == 1 else None

    def visit_Expr(self, node: ast.Expr):
        for qc in self.query_contexts:
            if node.value is qc.query.execute_node:
                self.current_qc = qc
                return None
        return self.generic_visit(node)

    def visit_If(self, node: ast.If):
        new_body = []
        for stmt in node.body:
            new_stmt = self.visit(stmt)
            if new_stmt is not None:
                new_body.append(new_stmt)
        new_orelse = []
        for stmt in node.orelse:
            new_stmt = self.visit(stmt)
            if new_stmt is not None:
                new_orelse.append(new_stmt)
        return ast.If(
            test=node.test,
            body=new_body if new_body else [ast.Pass()],
            orelse=new_orelse
        )

    def visit_Assign(self, node: ast.Assign):
        # 1. Check if node.value is / contains execute call
        for qc in self.query_contexts:
            if any(child is qc.query.execute_node for child in ast.walk(node.value)) or node.value is qc.query.execute_node:
                self.current_qc = qc
                node.value = ast.Call(
                    func=ast.Name(id="next", ctx=ast.Load()),
                    args=[
                        ast.Name(id=qc.iter_name, ctx=ast.Load()),
                        ast.Constant(value=None)
                    ],
                    keywords=[]
                )
                return self.generic_visit(node)

        # 2. Check if node.value is fetchone
        is_fetchone = (isinstance(node.value, ast.Call)
                       and isinstance(node.value.func, ast.Attribute)
                       and node.value.func.attr == "fetchone")
        if is_fetchone:
            qc = self.current_qc or self.query_contexts[0]
            node.value = ast.Call(
                func=ast.Name(id="next", ctx=ast.Load()),
                args=[
                    ast.Name(id=qc.iter_name, ctx=ast.Load()),
                    ast.Constant(value=None)
                ],
                keywords=[]
            )
            return self.generic_visit(node)

        # 3. Check if node.value is fetchall
        is_fetchall = (isinstance(node.value, ast.Call)
                       and isinstance(node.value.func, ast.Attribute)
                       and node.value.func.attr == "fetchall")
        if is_fetchall:
            qc = self.current_qc or self.query_contexts[0]
            node.value = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=qc.result_map_name, ctx=ast.Load()),
                    attr="get", ctx=ast.Load()
                ),
                args=[
                    ast.Name(id=qc.loop_var, ctx=ast.Load()),
                    ast.List(elts=[], ctx=ast.Load())
                ],
                keywords=[]
            )
            return self.generic_visit(node)

        return self.generic_visit(node)


class Phase2Transformer(Phase2MultiTransformer):
    """Backwards-compatible single-query Phase2 transformer."""
    def __init__(self, query: QueryInLoop, loop_var: str, result_map_name: str, iter_name: str):
        qc = QueryTransformContext(
            query=query,
            tid=0,
            params_name="",
            result_map_name=result_map_name,
            iter_name=iter_name,
            loop_var=loop_var,
            param_col="",
            bound_vars=ast.Tuple(elts=[], ctx=ast.Load())
        )
        super().__init__([qc])


class ASTTransformer(ast.NodeTransformer):
    def __init__(self, transformable_queries: list[QueryInLoop] | AnalysisResult, db_type: str, analysis: AnalysisResult | None = None):
        if isinstance(transformable_queries, AnalysisResult):
            self.analysis = transformable_queries
            self.transformable_queries = transformable_queries.transformable_queries
        else:
            self.analysis = analysis
            self.transformable_queries = transformable_queries
        self.db_type = db_type
        self.applied_rules = []
        self._dep = DependencyAnalyzer()
        self._id_counter = 0

        # Group transformable queries by loop node for single-pass multi-query splitting (Gap 2)
        self.queries_by_loop: dict[ast.AST, list[QueryInLoop]] = collections.defaultdict(list)
        for q in self.transformable_queries:
            self.queries_by_loop[q.loop_node].append(q)

    def _add_rule(self, rule: str):
        if rule not in self.applied_rules:
            self.applied_rules.append(rule)

    def _get_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    # ------------------------------------------------------------------ #
    # Visitors                                                           #
    # ------------------------------------------------------------------ #

    def visit_For(self, node: ast.For) -> ast.AST | list[ast.AST]:
        qs = self.queries_by_loop.get(node)
        if not qs:
            return self.generic_visit(node)
        return self._transform_for_multi(node, qs)

    def visit_While(self, node: ast.While) -> ast.AST | list[ast.AST]:
        qs = self.queries_by_loop.get(node)
        if not qs:
            return self.generic_visit(node)
        return self._transform_while_multi(node, qs)

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _extract_param_col(self, sql: str) -> str:
        m = re.search(r"([\w\.]+)\s*=\s*(?:%s|\?|%\(\w+\)s)", sql, re.IGNORECASE)
        return m.group(1) if m else ""
        
    def _get_bound_vars(self, query: QueryInLoop) -> ast.AST:
        if len(query.execute_node.args) > 1:
            return query.execute_node.args[1]
        return ast.Tuple(elts=[], ctx=ast.Load())

    def _build_execute_and_result_map(self, query: QueryInLoop, rewrite: Any, tid: int):
        """Return (execute_stmt, result_map_stmt, result_map_loop) AST nodes."""
        from src.query_rewriter import RewriteResult
        if isinstance(rewrite, RewriteResult):
            rewritten_sql = rewrite.sql
            key_index = rewrite.key_index
            key_prepended = rewrite.key_prepended
        else:
            rewritten_sql = str(rewrite)
            key_index = 0
            key_prepended = True

        cursor_var = query.execute_node.func.value
        params_name = f"_pyd_params_{tid}"
        result_map_name = f"_pyd_result_map_{tid}"

        if self.db_type == "sqlite":
            placeholders = ast.Call(
                func=ast.Attribute(value=ast.Constant(value=","), attr="join", ctx=ast.Load()),
                args=[ast.BinOp(
                    left=ast.Constant(value="?"),
                    op=ast.Mult(),
                    right=ast.Call(func=ast.Name(id="len", ctx=ast.Load()),
                                   args=[ast.Name(id=params_name, ctx=ast.Load())],
                                   keywords=[]),
                )],
                keywords=[],
            )
            sql_expr = ast.Call(
                func=ast.Attribute(value=ast.Constant(value=rewritten_sql), attr="format", ctx=ast.Load()),
                args=[placeholders], keywords=[],
            )
            exec_args = [sql_expr, ast.Name(id=params_name, ctx=ast.Load())]
        else:
            exec_args = [
                ast.Constant(value=rewritten_sql),
                ast.Tuple(elts=[ast.Name(id=params_name, ctx=ast.Load())], ctx=ast.Load()),
            ]

        execute_stmt = ast.Expr(value=ast.Call(
            func=query.execute_node.func,
            args=exec_args,
            keywords=query.execute_node.keywords,
        ))

        fetch_call = ast.Call(
            func=ast.Attribute(value=cursor_var, attr="fetchall", ctx=ast.Load()),
            args=[], keywords=[],
        )
        result_map_init = ast.Assign(
            targets=[ast.Name(id=result_map_name, ctx=ast.Store())],
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="collections", ctx=ast.Load()),
                    attr="defaultdict", ctx=ast.Load()
                ),
                args=[ast.Name(id="list", ctx=ast.Load())],
                keywords=[]
            )
        )
        
        # Use row[1:] if key_prepended else row
        if key_prepended:
            payload = ast.Subscript(
                value=ast.Name(id="row", ctx=ast.Load()),
                slice=ast.Slice(lower=ast.Constant(value=1), upper=None, step=None),
                ctx=ast.Load()
            )
        else:
            payload = ast.Name(id="row", ctx=ast.Load())
        
        result_map_loop = ast.For(
            target=ast.Name(id="row", ctx=ast.Store()),
            iter=fetch_call,
            body=[
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Subscript(
                                value=ast.Name(id=result_map_name, ctx=ast.Load()),
                                slice=ast.Subscript(
                                    value=ast.Name(id="row", ctx=ast.Load()),
                                    slice=ast.Constant(value=key_index),
                                    ctx=ast.Load()
                                ),
                                ctx=ast.Load()
                            ),
                            attr="append", ctx=ast.Load()
                        ),
                        args=[payload],
                        keywords=[]
                    )
                )
            ],
            orelse=[]
        )
        return execute_stmt, result_map_init, result_map_loop

    def _param_append(self, param_expr: ast.AST, list_name: str) -> ast.Expr:
        load_ctx = ast.Load()
        return ast.Expr(value=ast.Call(
            func=ast.Attribute(value=ast.Name(id=list_name, ctx=load_ctx),
                               attr="append", ctx=load_ctx),
            args=[param_expr],
            keywords=[],
        ))

    def _init_params(self, list_name: str) -> ast.Assign:
        return ast.Assign(
            targets=[ast.Name(id=list_name, ctx=ast.Store())],
            value=ast.List(elts=[], ctx=ast.Load()),
        )

    def _ctx_append(self, param_var: str, ctx_name: str) -> ast.Expr:
        load_ctx = ast.Load()
        return ast.Expr(value=ast.Call(
            func=ast.Attribute(value=ast.Name(id=ctx_name, ctx=load_ctx),
                               attr="append", ctx=load_ctx),
            args=[ast.Name(id=param_var, ctx=load_ctx)],
            keywords=[],
        ))

    def _get_stmt_order(self, query: QueryInLoop) -> list[int] | None:
        if self.analysis:
            if getattr(self.analysis, "stmt_order", None):
                return self.analysis.stmt_order
            if getattr(self.analysis, "stmtOrder", None):
                return self.analysis.stmtOrder
            if self.analysis.scirpy_facts and self.analysis.scirpy_facts.loops:
                exec_lineno = getattr(query.execute_node, "lineno", -1)
                for loop in self.analysis.scirpy_facts.loops:
                    for q in loop.queries:
                        if q.callLineno == exec_lineno:
                            if getattr(q, "stmtOrder", None):
                                return q.stmtOrder
                            if getattr(loop, "stmtOrder", None):
                                return loop.stmtOrder
                    if getattr(loop, "headLineno", -1) == getattr(query.loop_node, "lineno", -1):
                        if getattr(loop, "stmtOrder", None):
                            return loop.stmtOrder
        return None

    def _reorder_stmts(self, stmts: list[ast.AST], stmt_order: list[int] | None) -> list[ast.AST]:
        if not stmt_order:
            return stmts
        order_map = {lineno: i for i, lineno in enumerate(stmt_order)}
        return sorted(
            stmts,
            key=lambda s: order_map.get(getattr(s, "lineno", None), float("inf"))
        )

    # ------------------------------------------------------------------ #
    # For-loop multi-query transformation (Gap 2 & Gap 4/5)              #
    # ------------------------------------------------------------------ #

    def _transform_for_multi(self, loop: ast.For, queries: list[QueryInLoop]) -> list[ast.AST]:
        query_contexts: list[QueryTransformContext] = []
        for q in queries:
            tid = self._get_id()
            params_name = f"_pyd_params_{tid}"
            result_map_name = f"_pyd_result_map_{tid}"
            iter_name = f"_pyd_iter_{tid}"
            
            loop_var = q.loop_var
            if isinstance(loop_var, list):
                loop_var = loop_var[0]
            elif loop_var is None:
                loop_var = q.parameter_vars[0] if q.parameter_vars else "id"

            param_col = self._extract_param_col(q.query_string) or (
                q.parameter_vars[0] if q.parameter_vars else "id"
            )
            bound_vars = self._get_bound_vars(q)
            query_contexts.append(QueryTransformContext(
                query=q,
                tid=tid,
                params_name=params_name,
                result_map_name=result_map_name,
                iter_name=iter_name,
                loop_var=loop_var,
                param_col=param_col,
                bound_vars=bound_vars
            ))

        stmt_order = self._get_stmt_order(queries[0])
        
        self._add_rule("loop_splitting")
        self._add_rule("query_rewrite")

        # Check if all queries are DML without result dependency
        all_dml = all(q.is_dml and not q.has_result_dependency for q in queries)
        if all_dml:
            classifications = self._dep.classify_loop_stmts(
                loop.body,
                queries[0].execute_node,
                stmt_facts=self.analysis.stmt_facts if self.analysis else None,
                scirpy_facts=self.analysis.scirpy_facts if self.analysis else None,
            )
            pre_stmts = self._reorder_stmts([s for s, c in zip(loop.body, classifications) if c == "PRE"], stmt_order)
            post_stmts = self._reorder_stmts([s for s, c in zip(loop.body, classifications) if c == "POST"], stmt_order)
            if pre_stmts or post_stmts or (stmt_order and len(loop.body) > 1):
                self._add_rule("statement_reordering")
            if any(isinstance(stmt, ast.If) for stmt in loop.body):
                self._add_rule("conditional_handling")

            res = []
            for qc in query_contexts:
                res.append(self._init_params(qc.params_name))
            
            phase1_body = list(pre_stmts)
            for qc in query_contexts:
                phase1_body.append(self._param_append(qc.bound_vars, qc.params_name))
            phase1_loop = ast.For(
                target=loop.target, iter=loop.iter,
                body=phase1_body, orelse=[]
            )
            res.append(phase1_loop)
            for qc in query_contexts:
                sql_expr = qc.query.execute_node.args[0]
                cursor_var = qc.query.execute_node.func.value
                executemany_stmt = ast.Expr(value=ast.Call(
                    func=ast.Attribute(value=cursor_var, attr="executemany", ctx=ast.Load()),
                    args=[sql_expr, ast.Name(id=qc.params_name, ctx=ast.Load())],
                    keywords=[]
                ))
                res.append(executemany_stmt)
            if post_stmts:
                phase2_loop = ast.For(
                    target=loop.target, iter=loop.iter,
                    body=post_stmts, orelse=loop.orelse,
                )
                res.append(phase2_loop)
            return res

        # Classify statements
        classifications = self._dep.classify_loop_stmts(
            loop.body,
            queries[0].execute_node,
            stmt_facts=self.analysis.stmt_facts if self.analysis else None,
            scirpy_facts=self.analysis.scirpy_facts if self.analysis else None,
        )

        has_guard = any(
            isinstance(stmt, ast.If) and any(
                any(child is qc.query.execute_node for child in ast.walk(stmt))
                for qc in query_contexts
            )
            for stmt in loop.body
        )
        if has_guard:
            self._add_rule("conditional_handling")

        pre_stmts = self._reorder_stmts([s for s, c in zip(loop.body, classifications) if c == "PRE"], stmt_order)
        if pre_stmts or (stmt_order and len(loop.body) > 1):
            self._add_rule("statement_reordering")

        # Batch queries and result maps
        batch_nodes = []
        for qc in query_contexts:
            if qc.query.is_dml and not qc.query.has_result_dependency:
                sql_expr = qc.query.execute_node.args[0]
                cursor_var = qc.query.execute_node.func.value
                executemany_stmt = ast.Expr(value=ast.Call(
                    func=ast.Attribute(value=cursor_var, attr="executemany", ctx=ast.Load()),
                    args=[sql_expr, ast.Name(id=qc.params_name, ctx=ast.Load())],
                    keywords=[]
                ))
                batch_nodes.append(executemany_stmt)
            else:
                rewritten_sql = QueryRewriter().rewrite_for_batch(
                    qc.query.query_string, qc.param_col, self.db_type
                )
                exec_stmt, res_init, res_loop = self._build_execute_and_result_map(qc.query, rewritten_sql, qc.tid)
                batch_nodes.extend([exec_stmt, res_init, res_loop])

        # Phase 1: Collect parameters
        if not pre_stmts and not has_guard and all(not qc.query.is_dml for qc in query_contexts):
            collect_init_nodes = []
            for qc in query_contexts:
                collect_init_nodes.append(ast.Assign(
                    targets=[ast.Name(id=qc.params_name, ctx=ast.Store())],
                    value=ast.ListComp(
                        elt=ast.Name(id=qc.loop_var, ctx=ast.Load()),
                        generators=[
                            ast.comprehension(
                                target=loop.target,
                                iter=loop.iter,
                                ifs=[],
                                is_async=0
                            )
                        ]
                    )
                ))
            phase1_nodes = collect_init_nodes
        else:
            phase1_nodes = [self._init_params(qc.params_name) for qc in query_contexts]
            phase1_body = list(pre_stmts)
            for stmt in loop.body:
                if isinstance(stmt, ast.If):
                    qcs_in_if = [qc for qc in query_contexts if any(child is qc.query.execute_node for child in ast.walk(stmt))]
                    if qcs_in_if:
                        if_body = []
                        for qc in qcs_in_if:
                            param_expr = qc.bound_vars if qc.query.is_dml else ast.Name(id=qc.loop_var, ctx=ast.Load())
                            if_body.append(self._param_append(param_expr, qc.params_name))
                        phase1_body.append(ast.If(test=stmt.test, body=if_body, orelse=[]))
                else:
                    for qc in query_contexts:
                        if stmt is qc.query.execute_node or any(child is qc.query.execute_node for child in ast.walk(stmt)):
                            param_expr = qc.bound_vars if qc.query.is_dml else ast.Name(id=qc.loop_var, ctx=ast.Load())
                            phase1_body.append(self._param_append(param_expr, qc.params_name))
            phase1_for = ast.For(
                target=loop.target, iter=loop.iter,
                body=phase1_body if phase1_body else [ast.Pass()],
                orelse=[]
            )
            phase1_nodes.append(phase1_for)

        # Phase 2: Process results (Replay Loop)
        phase2_trans = Phase2MultiTransformer(query_contexts)
        phase2_body = []
        for qc in query_contexts:
            if not (qc.query.is_dml and not qc.query.has_result_dependency):
                iter_init = ast.Assign(
                    targets=[ast.Name(id=qc.iter_name, ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Name(id="iter", ctx=ast.Load()),
                        args=[
                            ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id=qc.result_map_name, ctx=ast.Load()),
                                    attr="get", ctx=ast.Load()
                                ),
                                args=[
                                    ast.Name(id=qc.loop_var, ctx=ast.Load()),
                                    ast.List(elts=[], ctx=ast.Load())
                                ],
                                keywords=[]
                            )
                        ],
                        keywords=[]
                    )
                )
                phase2_body.append(iter_init)

        ordered_stmts = self._reorder_stmts(loop.body, stmt_order)
        for stmt in ordered_stmts:
            new_stmt = phase2_trans.visit(stmt)
            if new_stmt is not None:
                phase2_body.append(new_stmt)

        phase2_loop = ast.For(
            target=loop.target, iter=loop.iter,
            body=phase2_body if phase2_body else [ast.Pass()],
            orelse=loop.orelse,
        )

        return phase1_nodes + batch_nodes + [phase2_loop]

    # ------------------------------------------------------------------ #
    # While-loop multi-query transformation (Gap 2 & Gap 4/5)            #
    # ------------------------------------------------------------------ #

    def _transform_while_multi(self, loop: ast.While, queries: list[QueryInLoop]) -> list[ast.AST]:
        cond_vars = sorted(
            {n.id for n in ast.walk(loop.test)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        )
        
        query_contexts: list[QueryTransformContext] = []
        for q in queries:
            tid = self._get_id()
            params_name = f"_pyd_params_{tid}"
            result_map_name = f"_pyd_result_map_{tid}"
            iter_name = f"_pyd_iter_{tid}"
            
            param_var = q.parameter_vars[0] if q.parameter_vars else (cond_vars[0] if cond_vars else "v")
            param_col = self._extract_param_col(q.query_string) or param_var
            bound_vars = self._get_bound_vars(q)
            
            query_contexts.append(QueryTransformContext(
                query=q,
                tid=tid,
                params_name=params_name,
                result_map_name=result_map_name,
                iter_name=iter_name,
                loop_var=param_var,
                param_col=param_col,
                bound_vars=bound_vars
            ))

        main_tid = query_contexts[0].tid
        ctx_name = f"_pyd_ctx_{main_tid}"
        ctx_init = ast.Assign(
            targets=[ast.Name(id=ctx_name, ctx=ast.Store())],
            value=ast.List(elts=[], ctx=ast.Load())
        )

        stmt_order = self._get_stmt_order(queries[0])
        self._add_rule("loop_splitting")
        self._add_rule("query_rewrite")

        classifications = self._dep.classify_loop_stmts(
            loop.body,
            queries[0].execute_node,
            condition_vars=set(cond_vars),
            stmt_facts=self.analysis.stmt_facts if self.analysis else None,
            scirpy_facts=self.analysis.scirpy_facts if self.analysis else None,
        )

        pre_stmts = self._reorder_stmts([s for s, c in zip(loop.body, classifications) if c == "PRE"], stmt_order)
        adv_stmts = self._reorder_stmts([s for s, c in zip(loop.body, classifications) if c == "ADVANCE"], stmt_order)
        if pre_stmts or adv_stmts or (stmt_order and len(loop.body) > 1):
            self._add_rule("statement_reordering")
        
        has_guard = any(
            isinstance(stmt, ast.If) and any(
                any(child is qc.query.execute_node for child in ast.walk(stmt))
                for qc in query_contexts
            )
            for stmt in loop.body
        )
        if has_guard:
            self._add_rule("conditional_handling")

        # Determine context variable (LoopContextTable)
        ctx_var = None
        for s in pre_stmts:
            defs = self._dep._get_defs(s, stmt_facts=self.analysis.stmt_facts if self.analysis else None)
            if defs:
                ctx_var = sorted(defs)[0]
                break
        if not ctx_var:
            ctx_var = query_contexts[0].loop_var

        # Phase 1: collect params & record context table
        phase1_nodes = [self._init_params(qc.params_name) for qc in query_contexts]
        phase1_nodes.append(ctx_init)

        phase1_body = list(pre_stmts)
        for stmt in loop.body:
            if isinstance(stmt, ast.If):
                qcs_in_if = [qc for qc in query_contexts if any(child is qc.query.execute_node for child in ast.walk(stmt))]
                if qcs_in_if:
                    if_body = []
                    for qc in qcs_in_if:
                        param_expr = qc.bound_vars if qc.query.is_dml else ast.Name(id=qc.loop_var, ctx=ast.Load())
                        if_body.append(self._param_append(param_expr, qc.params_name))
                    phase1_body.append(ast.If(test=stmt.test, body=if_body, orelse=[]))
            else:
                for qc in query_contexts:
                    if stmt is qc.query.execute_node or any(child is qc.query.execute_node for child in ast.walk(stmt)):
                        param_expr = qc.bound_vars if qc.query.is_dml else ast.Name(id=qc.loop_var, ctx=ast.Load())
                        phase1_body.append(self._param_append(param_expr, qc.params_name))
        
        phase1_body.append(self._ctx_append(ctx_var, ctx_name))
        phase1_body.extend(adv_stmts)

        phase1_loop = ast.While(test=loop.test, body=phase1_body if phase1_body else [ast.Pass()], orelse=[])
        phase1_nodes.append(phase1_loop)

        # Batch queries and result maps
        batch_nodes = []
        for qc in query_contexts:
            if qc.query.is_dml and not qc.query.has_result_dependency:
                sql_expr = qc.query.execute_node.args[0]
                cursor_var = qc.query.execute_node.func.value
                executemany_stmt = ast.Expr(value=ast.Call(
                    func=ast.Attribute(value=cursor_var, attr="executemany", ctx=ast.Load()),
                    args=[sql_expr, ast.Name(id=qc.params_name, ctx=ast.Load())],
                    keywords=[]
                ))
                batch_nodes.append(executemany_stmt)
            else:
                rewritten_sql = QueryRewriter().rewrite_for_batch(
                    qc.query.query_string, qc.param_col, self.db_type
                )
                exec_stmt, res_init, res_loop = self._build_execute_and_result_map(qc.query, rewritten_sql, qc.tid)
                batch_nodes.extend([exec_stmt, res_init, res_loop])

        # Phase 2: Process results (Replay Loop with Conditional Merge-Back)
        phase2_trans = Phase2MultiTransformer(query_contexts)
        phase2_body = []
        for qc in query_contexts:
            if not (qc.query.is_dml and not qc.query.has_result_dependency):
                iter_init = ast.Assign(
                    targets=[ast.Name(id=qc.iter_name, ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Name(id="iter", ctx=ast.Load()),
                        args=[
                            ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id=qc.result_map_name, ctx=ast.Load()),
                                    attr="get", ctx=ast.Load()
                                ),
                                args=[
                                    ast.Name(id=ctx_var, ctx=ast.Load()),
                                    ast.List(elts=[], ctx=ast.Load())
                                ],
                                keywords=[]
                            )
                        ],
                        keywords=[]
                    )
                )
                phase2_body.append(iter_init)

        ordered_stmts = self._reorder_stmts(loop.body, stmt_order)
        for stmt in ordered_stmts:
            if stmt in pre_stmts or stmt in adv_stmts:
                continue
            new_stmt = phase2_trans.visit(stmt)
            if new_stmt is not None:
                phase2_body.append(new_stmt)

        phase2_loop = ast.For(
            target=ast.Name(id=ctx_var, ctx=ast.Store()),
            iter=ast.Name(id=ctx_name, ctx=ast.Load()),
            body=phase2_body if phase2_body else [ast.Pass()],
            orelse=loop.orelse,
        )

        return phase1_nodes + batch_nodes + [phase2_loop]


def apply_transformations(analysis: AnalysisResult, db_type: str) -> TransformedIR:
    tree = getattr(analysis, "tree", None)
    if not tree:
        raise ValueError("AST tree not found in AnalysisResult")
    transformer = ASTTransformer(analysis, db_type)
    transformed_tree = transformer.visit(tree)
    ast.fix_missing_locations(transformed_tree)
    return TransformedIR(
        original_ast=tree,
        transformed_ast=transformed_tree,
        applied_rules=transformer.applied_rules,
    )
