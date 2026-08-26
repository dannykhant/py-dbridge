"""Rewrite SQL queries for set-oriented execution.

Transforms parameterized queries from single-row form to batch form:
  - WHERE col = %s  →  WHERE col = ANY(%s)
  - WHERE col = %(name)s  →  WHERE col = ANY(%(name)s)
  - WHERE col = ? (SQLite)  →  WHERE col IN ({})
"""
import re
from dataclasses import dataclass
from typing import Optional
from .scirpy_bridge import eqsql_optimize_query


@dataclass
class RewriteResult:
    sql: str
    key_index: int = 0
    key_prepended: bool = False
    payload_slice: Optional[slice] = None

    def __contains__(self, item: str) -> bool:
        return item in self.sql

    def __str__(self) -> str:
        return self.sql

    def __repr__(self) -> str:
        return f"RewriteResult(sql={self.sql!r}, key_index={self.key_index}, key_prepended={self.key_prepended}, payload_slice={self.payload_slice})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.sql == other
        if isinstance(other, RewriteResult):
            return (
                self.sql == other.sql
                and self.key_index == other.key_index
                and self.key_prepended == other.key_prepended
                and self.payload_slice == other.payload_slice
            )
        return False


def _split_select_columns(select_clause: str) -> list[str]:
    cols = []
    current = []
    depth = 0
    for char in select_clause:
        if char == '(':
            depth += 1
            current.append(char)
        elif char == ')':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            cols.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        cols.append(''.join(current).strip())
    return cols


def _extract_column_identifiers(col_str: str) -> set[str]:
    col_str = col_str.strip()
    if col_str == "*" or col_str.endswith(".*"):
        return set()
    
    # Matches:
    # 1) [qualifier.]col [AS alias] or [qualifier.]col [alias]
    # e.g., p.id AS item_id, id AS item_id, p.id item_id, p.item_id, item_id
    m = re.match(r"^(?:([\w\.]+)\.)?(\w+)(?:\s+(?:AS\s+)?(\w+))?$", col_str, re.IGNORECASE)
    if not m:
        # Check if it's an expression with an alias: e.g. UPPER(p.id) AS item_id or func(col) alias
        m_alias = re.search(r"(?i)\b(?:AS\s+)?(\w+)\s*$", col_str)
        if m_alias:
            return {m_alias.group(1).lower()}
        return set()
    
    qualifier, col_name, alias = m.groups()
    names = set()
    if col_name:
        names.add(col_name.lower())
    if qualifier and col_name:
        full_qual = f"{qualifier}.{col_name}".lower()
        names.add(full_qual)
        parts = qualifier.split('.')
        if len(parts) > 1:
            names.add(f"{parts[-1]}.{col_name}".lower())
    if alias:
        names.add(alias.lower())
    return names


def _extract_param_identifiers(param_column: str) -> set[str]:
    if not param_column:
        return set()
    param = param_column.strip()
    names = {param.lower()}
    if "." in param:
        parts = param.split(".")
        names.add(parts[-1].lower())
        if len(parts) > 2:
            names.add(f"{parts[-2]}.{parts[-1]}".lower())
    return names


class QueryRewriter:
    """Rewrite SQL queries for set-oriented execution."""

    def rewrite_for_batch(self, sql: str, param_column: str,
                          db_type: str = "postgres") -> RewriteResult:
        """Rewrite a single-parameter query to accept a batch of parameters."""
        if not sql:
            return RewriteResult(sql=sql, key_index=0, key_prepended=False, payload_slice=None)

        upper_sql = sql.strip().upper()
        if upper_sql.startswith(("INSERT", "UPDATE", "DELETE")):
            return RewriteResult(sql=sql, key_index=0, key_prepended=False, payload_slice=None)

        # Check if param_column was in original sql SELECT clause
        orig_had_key = False
        orig_key_index = 0
        param_idents = _extract_param_identifiers(param_column)
        orig_match = re.match(r"(?i)^\s*SELECT\s+(.*?)\s+FROM\s+", sql, flags=re.DOTALL)
        if orig_match and param_column:
            orig_clause = orig_match.group(1)
            orig_cols = _split_select_columns(orig_clause)
            for idx, col in enumerate(orig_cols):
                col_str = col.strip()
                if col_str == "*" or col_str.endswith(".*"):
                    continue
                col_idents = _extract_column_identifiers(col_str)
                if col_idents & param_idents:
                    orig_had_key = True
                    orig_key_index = idx
                    break

        sql_to_rewrite = sql
        optimized = eqsql_optimize_query(sql, db_type)
        if optimized and optimized != sql:
            sql_to_rewrite = optimized

        if orig_had_key:
            key_index = orig_key_index
            key_prepended = False
            payload_slice = None
            # If EqSQL prepended key when orig already had it, remove the extra key at front
            for cand in sorted(param_idents, key=len, reverse=True):
                dup_two_pattern = rf"(?i)^\s*SELECT\s+{re.escape(cand)},\s+{re.escape(cand)},\s*"
                dup_one_pattern = rf"(?i)^\s*SELECT\s+{re.escape(cand)},\s*"
                if re.match(dup_two_pattern, sql_to_rewrite):
                    sql_to_rewrite = re.sub(rf"(?i)^(\s*SELECT\s+){re.escape(cand)},\s*", r"\1", sql_to_rewrite, count=1)
                    break
                elif re.match(dup_one_pattern, sql_to_rewrite) and not re.match(dup_one_pattern, sql):
                    sql_to_rewrite = re.sub(dup_one_pattern, "SELECT ", sql_to_rewrite, count=1)
                    break
        else:
            key_index = 0
            key_prepended = True
            payload_slice = slice(1, None)
            # Check if sql_to_rewrite already has param_column anywhere in SELECT (e.g. from EqSQL)
            check_match = re.match(r"(?i)^\s*SELECT\s+(.*?)\s+FROM\s+", sql_to_rewrite, flags=re.DOTALL)
            has_prepended = False
            if check_match and param_column:
                check_clause = check_match.group(1)
                check_cols = _split_select_columns(check_clause)
                for idx, col in enumerate(check_cols):
                    col_str = col.strip()
                    if col_str == "*" or col_str.endswith(".*"):
                        continue
                    col_idents = _extract_column_identifiers(col_str)
                    if col_idents & param_idents:
                        has_prepended = True
                        key_index = idx
                        if idx == 0:
                            payload_slice = slice(1, None)
                        else:
                            key_prepended = False
                            payload_slice = None
                        break
            if not has_prepended and param_column:
                sql_to_rewrite = re.sub(r"(?i)^(\s*SELECT\s+)", rf"\g<1>{param_column}, ", sql_to_rewrite, count=1)

        param_candidates = sorted(param_idents, key=len, reverse=True) if param_idents else ([param_column] if param_column else [])
        col_pattern = "|".join(re.escape(c) for c in param_candidates) if param_candidates else ""

        if col_pattern:
            if db_type == "postgres":
                # Match col = %s
                pattern_pos = rf"(?i)\b({col_pattern})\s*=\s*%s"
                if re.search(pattern_pos, sql_to_rewrite):
                    sql_to_rewrite = re.sub(pattern_pos, r"\1 = ANY(%s)", sql_to_rewrite, flags=re.IGNORECASE)
                else:
                    # Match col = %(name)s
                    pattern_named = rf"(?i)\b({col_pattern})\s*=\s*%\((\w+)\)s"
                    if re.search(pattern_named, sql_to_rewrite):
                        sql_to_rewrite = re.sub(pattern_named, r"\1 = ANY(%(\2)s)", sql_to_rewrite, flags=re.IGNORECASE)

            elif db_type == "sqlite":
                # Match col = ?
                pattern_sqlite = rf"(?i)\b({col_pattern})\s*=\s*\?"
                if re.search(pattern_sqlite, sql_to_rewrite):
                    sql_to_rewrite = re.sub(pattern_sqlite, r"\1 IN ({})", sql_to_rewrite, flags=re.IGNORECASE)

        has_aggregate = bool(re.search(r"(?i)\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", sql_to_rewrite))
        if has_aggregate and not re.search(r"(?i)\bGROUP BY\b", sql_to_rewrite) and param_column:
            sql_to_rewrite += f" GROUP BY {param_column}"

        return RewriteResult(
            sql=sql_to_rewrite,
            key_index=key_index,
            key_prepended=key_prepended,
            payload_slice=payload_slice
        )
