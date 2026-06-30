# -*- coding: utf-8 -*-
"""
Combined Semantics variable classifier (Sara Cohen, PODS 2006).

Traverses a mo_sql_parsing AST top-down to classify every relation
referenced by a query as contributing either BAG (multiset) variables
or SET variables under Combined Semantics.

Core idea
---------
Each variable in a query body is either a *multiset (BAG) variable* —
whose different assignments contribute independently to the multiplicity
of an output tuple — or a *set variable* — whose assignments collapse
and do not increase multiplicity.  In SQL:

  - Relations in the main FROM clause of a plain SELECT → BAG context.
  - Relations inside EXISTS / NOT EXISTS / IN / NOT IN / ANY subqueries
    → SET context (they act as existence filters, not multiplicity sources).
  - Relations inside a SELECT DISTINCT subquery → SET context (duplicates
    are eliminated, so different assignments for inner variables collapse).
  - Relations in a scalar subquery (SELECT clause, CASE/IF expression) →
    SET context (they return a single value, not a multiplicity stream).
  - UNION (set union, removes duplicates) → SET context for each branch.
  - UNION ALL, INTERSECT, INTERSECT ALL, EXCEPT, EXCEPT ALL, and all JOIN
    variants pass the current context unchanged (per spec).

Output
------
  analyze(sql_or_ast) → dict[str, list[str]]

  {alias_or_table_name: [column, ...]}

  - BAG context  →  column list contains every schema column of the relation.
  - SET context  →  column list is empty (relation contributes 0 multiplicity).
"""

from __future__ import annotations

import re
from typing import Any

import mo_sql_parsing


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class SemanticsAnalyzer:
    """
    Top-down / bottom-up AST traversal implementing Combined Semantics
    variable classification.

    Parameters
    ----------
    schema : dict
        Schema dict as stored in the benchmark, e.g.
        {"CUSTOMERS": {"ID": "INT", "NAME": "VARCHAR"}, ...}
    """

    SET = "SET"
    BAG = "BAG"

    # mo_sql_parsing join-variant keys (all pass context through)
    _JOIN_KEYS = frozenset({
        'join', 'inner join',
        'left join', 'left outer join',
        'right join', 'right outer join',
        'full join', 'full outer join',
        'cross join',
    })

    # Top-level set-operation keys
    _SET_OPS_ELIMINATE = frozenset({'union'})                      # → SET context
    _SET_OPS_PRESERVE  = frozenset({                               # → pass context
        'union_all', 'union_distinct',
        'intersect', 'intersect_all',
        'except', 'except_all',
    })

    def __init__(self, schema: dict):
        self.schema: dict[str, dict[str, str]] = {
            k.upper(): {c.upper(): t for c, t in v.items()}
            for k, v in (schema or {}).items()
        }
        # Set during analyze_with_key_filter; used in _register to filter PK
        # columns at the leaf level so the filter propagates through derived
        # table and CTE aliases automatically.  None when not active.
        self._single_pk_cols: dict[str, set] | None = None
        # Kept for alias→table tracking (used by the post-processing loop).
        self._alias_to_table: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, sql_or_ast: str | dict) -> dict[str, list[str]]:
        """
        Classify all relations referenced by the query.

        Parameters
        ----------
        sql_or_ast : str or dict
            A SQL string or a pre-parsed mo_sql_parsing AST dict.

        Returns
        -------
        dict[str, list[str]]
            ``{alias_or_table_name: [column, ...]}``
            Empty column list → relation is in SET context.
            Non-empty column list → relation is in BAG context;
            the list contains all schema columns.
        """
        if isinstance(sql_or_ast, str):
            ast = mo_sql_parsing.parse(sql_or_ast.upper())
        else:
            ast = sql_or_ast

        result: dict[str, list[str]] = {}
        self._visit_query(ast, self.BAG, result, cte_map={})
        return result

    def analyze_with_key_filter(
        self,
        sql_or_ast: str | dict,
        constraints: list,
    ) -> dict[str, list[str]]:
        """
        Like analyze(), but removes single-column primary-key columns from
        each relation's BAG variable list.

        A single-column PK acts like a set key — each value appears at most
        once — so it does not contribute to output multiplicity.  A composite
        PK does NOT guarantee individual column uniqueness, so those columns
        are kept.

        Parameters
        ----------
        sql_or_ast : str or dict
            SQL string or pre-parsed AST.
        constraints : list
            Constraint list from the benchmark record, e.g.
            [{"primary": [{"value": "TABLE__COL"}]}, ...]

        Returns
        -------
        dict[str, list[str]]
            Same format as analyze(), with single-PK columns removed.
        """
        # Filter is applied at leaf registration (_register) so it propagates
        # automatically through derived-table and CTE aliases.
        self._single_pk_cols = _parse_single_pk_columns(constraints)
        self._alias_to_table = {}
        try:
            result = self.analyze(sql_or_ast)
        finally:
            self._alias_to_table = None
            self._single_pk_cols = None
        return result

    def count_bag_variables(self, sql_or_ast: str | dict) -> int:
        """Total BAG variable slots across all relations in the query."""
        mapping = self.analyze(sql_or_ast)
        return sum(len(cols) for cols in mapping.values())

    def count_bag_variables_filtered(
        self,
        sql_or_ast: str | dict,
        constraints: list,
    ) -> int:
        """Total BAG variable slots after single-column PK columns are removed."""
        mapping = self.analyze_with_key_filter(sql_or_ast, constraints)
        return sum(len(cols) for cols in mapping.values())

    # ------------------------------------------------------------------
    # Fast-rejection heuristic (Lemma 4.1, Sara Cohen PODS 2006)
    # ------------------------------------------------------------------

    RESULT_NOT_EQUIVALENT = "NOT_EQUIVALENT"
    RESULT_MAYBE_EQUIVALENT = "MAYBE_EQUIVALENT"

    def fast_path_equivalence_check(
        self,
        query1: str | dict,
        query2: str | dict,
        constraints: list,
    ) -> str:
        """
        Fast rejection check based on Combined Semantics BAG variable counts.

        By Lemma 4.1 (Sara Cohen, PODS 2006), two queries can only be
        equivalent under combined semantics if their sets of BAG (multiset)
        variables are in a specific correspondence.  A necessary (but not
        sufficient) condition is that the total number of BAG variable slots
        — after removing single-column primary-key columns — must be equal.

        The theory applies only to Conjunctive Queries (CQ): plain
        SELECT-FROM-WHERE with positive joins and existence filters.  If
        either query contains aggregation (GROUP BY, HAVING, COUNT/SUM/…),
        set operations (UNION, INTERSECT, EXCEPT), or negation (NOT IN,
        NOT EXISTS), the check is outside scope and ``"MAYBE_EQUIVALENT"``
        is returned without applying the lemma.

        Parameters
        ----------
        query1, query2 : str or dict
            SQL strings or pre-parsed ASTs.
        constraints : list
            Benchmark constraint list shared by both queries.

        Returns
        -------
        str
            ``"NOT_EQUIVALENT"``  if BAG variable counts differ (proven non-equivalent).
            ``"MAYBE_EQUIVALENT"`` if counts match or either query is out of CQ scope.
        """
        q1_sql = query1 if isinstance(query1, str) else mo_sql_parsing.format(query1)
        q2_sql = query2 if isinstance(query2, str) else mo_sql_parsing.format(query2)
        if not _is_cq_scoped(q1_sql) or not _is_cq_scoped(q2_sql):
            return self.RESULT_MAYBE_EQUIVALENT

        count1 = self.count_bag_variables_filtered(query1, constraints)
        count2 = self.count_bag_variables_filtered(query2, constraints)
        if count1 != count2:
            return self.RESULT_NOT_EQUIVALENT
        return self.RESULT_MAYBE_EQUIVALENT

    # ------------------------------------------------------------------
    # Query-level dispatch
    # ------------------------------------------------------------------

    def _visit_query(
        self,
        node: Any,
        context: str,
        result: dict,
        cte_map: dict,
    ) -> None:
        """Dispatch on the kind of query node."""
        if not isinstance(node, dict):
            return

        # Resolve WITH (CTE) definitions first; they are registered in a
        # local map so that when FROM references a CTE name we can expand it.
        local_cte = dict(cte_map)
        if 'with' in node:
            for clause in _ensure_list(node['with']):
                name = clause.get('name', '')
                if isinstance(name, dict):          # WITH name(cols) AS ...
                    name = next(iter(name))
                local_cte[str(name).upper()] = clause.get('value', {})

        # ------ SELECT / SELECT DISTINCT ------
        if 'select' in node or 'select_distinct' in node:
            # Distinct(Q) is a state-changer: switch inner context to SET
            inner = self.SET if 'select_distinct' in node else context

            if 'from' in node:
                self._visit_from(node['from'], inner, result, local_cte)

            if 'where' in node:
                self._visit_predicate(node['where'], inner, result, local_cte)

            if 'having' in node:
                self._visit_predicate(node['having'], inner, result, local_cte)

            # Scalar subqueries embedded in SELECT expressions → SET context
            sel = node.get('select') or node.get('select_distinct')
            self._visit_select_expressions(sel, result, local_cte)

            return

        # ------ Set operations ------
        for op in self._SET_OPS_ELIMINATE:
            if op in node:
                for sub in _ensure_list(node[op]):
                    self._visit_query(sub, self.SET, result, local_cte)
                return

        for op in self._SET_OPS_PRESERVE:
            if op in node:
                for sub in _ensure_list(node[op]):
                    self._visit_query(sub, context, result, local_cte)
                return

        # ------ Bare FROM (e.g. VALUES or aliased subquery without SELECT) ------
        if 'from' in node:
            self._visit_from(node['from'], context, result, local_cte)

    # ------------------------------------------------------------------
    # FROM clause
    # ------------------------------------------------------------------

    def _visit_from(
        self,
        from_node: Any,
        context: str,
        result: dict,
        cte_map: dict,
    ) -> None:
        if isinstance(from_node, str):
            self._register(from_node, from_node, context, result, cte_map)
        elif isinstance(from_node, list):
            for item in from_node:
                self._visit_from_item(item, context, result, cte_map)
        elif isinstance(from_node, dict):
            self._visit_from_item(from_node, context, result, cte_map)

    def _visit_from_item(
        self,
        item: Any,
        context: str,
        result: dict,
        cte_map: dict,
    ) -> None:
        """Handle one element of a FROM list (table, aliased table, subquery, join)."""
        if isinstance(item, str):
            self._register(item, item, context, result, cte_map)
            return

        if not isinstance(item, dict):
            return

        # Aliased table or subquery:  {value: "TABLE"|{subquery}, name: "alias"}
        if 'value' in item:
            value = item['value']
            alias = item.get('name')
            if isinstance(alias, dict):
                alias = next(iter(alias))          # WITH(col_list) alias
            alias = str(alias).upper() if alias else None

            if isinstance(value, str):
                self._register(value, alias or value, context, result, cte_map)

            elif isinstance(value, dict):
                # Subquery used as a derived table.
                # We traverse it, then expose results under the alias if given.
                if alias:
                    sub: dict[str, list] = {}
                    self._visit_query(value, context, sub, cte_map)
                    # Aggregate: alias maps to the union of all BAG columns found
                    # inside the derived table (or [] if in SET context).
                    if context == self.SET:
                        result[alias] = []
                    else:
                        result[alias] = sorted({c for cols in sub.values() for c in cols})
                else:
                    self._visit_query(value, context, result, cte_map)
            return

        # Join dict:  {'inner join': target, 'on': condition, 'using': ...}
        for jk in self._JOIN_KEYS:
            if jk in item:
                self._visit_from(item[jk], context, result, cte_map)
                if 'on' in item:
                    # ON clause can contain correlated subqueries (rare but possible)
                    self._visit_predicate(item['on'], context, result, cte_map)
                return

    # ------------------------------------------------------------------
    # Predicate / WHERE / HAVING
    # ------------------------------------------------------------------

    def _visit_predicate(
        self,
        pred: Any,
        context: str,
        result: dict,
        cte_map: dict,
    ) -> None:
        """
        Walk a predicate tree looking for subqueries.
        Switches context to SET for existence / membership constructs.
        Non-subquery operands are skipped.
        """
        if not isinstance(pred, dict):
            return

        for key, val in pred.items():

            # --- EXISTS(subquery) → SET ---
            if key == 'exists':
                if isinstance(val, dict) and _is_query(val):
                    self._visit_query(val, self.SET, result, cte_map)
                else:
                    self._visit_predicate(val, self.SET, result, cte_map)

            # --- NOT EXISTS  represented as {'not': {'exists': ...}} ---
            elif key == 'not':
                if isinstance(val, dict):
                    if 'exists' in val:
                        self._visit_query(val['exists'], self.SET, result, cte_map)
                    else:
                        self._visit_predicate(val, context, result, cte_map)
                elif isinstance(val, list):
                    for child in val:
                        self._visit_predicate(child, context, result, cte_map)

            # --- IN / NOT IN → SET for the subquery operand ---
            elif key in ('in', 'nin'):
                operands = val if isinstance(val, list) else [val]
                # operands[0] = LHS expression, operands[1] = subquery or value list
                if len(operands) >= 2:
                    rhs = operands[1]
                    if isinstance(rhs, dict) and _is_query(rhs):
                        self._visit_query(rhs, self.SET, result, cte_map)

            # --- = ANY / != ANY / > ANY etc. → SET ---
            elif key in ('any', 'some', 'all'):
                if isinstance(val, dict) and _is_query(val):
                    self._visit_query(val, self.SET, result, cte_map)

            # --- Logical connectives: recurse without changing context ---
            elif key in ('and', 'or'):
                for child in _ensure_list(val):
                    self._visit_predicate(child, context, result, cte_map)

            # --- IS NULL / IS NOT NULL used as NOT EXISTS analogue ---
            elif key in ('missing', 'isnull'):
                if isinstance(val, dict) and _is_query(val):
                    self._visit_query(val, self.SET, result, cte_map)

            # --- IF / CASE: scan branches for embedded subqueries ---
            elif key in ('if', 'case'):
                for child in _ensure_list(val):
                    if isinstance(child, dict):
                        if _is_query(child):
                            # scalar subquery in THEN/ELSE → SET context
                            self._visit_query(child, self.SET, result, cte_map)
                        else:
                            # could be a nested predicate (WHEN clause)
                            self._visit_predicate(child, context, result, cte_map)

            # --- Generic: any other operator whose operands may hide subqueries ---
            elif isinstance(val, list):
                for child in val:
                    if isinstance(child, dict):
                        if _is_query(child):
                            # Scalar correlated subquery used as a value → SET
                            self._visit_query(child, self.SET, result, cte_map)
                        else:
                            self._visit_predicate(child, context, result, cte_map)
            elif isinstance(val, dict):
                if _is_query(val):
                    self._visit_query(val, self.SET, result, cte_map)
                else:
                    self._visit_predicate(val, context, result, cte_map)

    # ------------------------------------------------------------------
    # SELECT clause expressions (scalar subqueries → SET)
    # ------------------------------------------------------------------

    def _visit_select_expressions(
        self,
        select_val: Any,
        result: dict,
        cte_map: dict,
    ) -> None:
        """Scan SELECT expressions for embedded scalar subqueries."""
        if select_val is None or select_val == '*':
            return
        for item in _ensure_list(select_val):
            if isinstance(item, dict):
                inner = item.get('value', item)
                if isinstance(inner, dict):
                    if _is_query(inner):
                        self._visit_query(inner, self.SET, result, cte_map)
                    else:
                        # e.g. IF(EXISTS(...), (SELECT ...), NULL)
                        self._visit_predicate(inner, self.SET, result, cte_map)

    # ------------------------------------------------------------------
    # Relation leaf registration
    # ------------------------------------------------------------------

    def _register(
        self,
        table_name: str,
        alias: str | None,
        context: str,
        result: dict,
        cte_map: dict,
    ) -> None:
        """
        Register one relation leaf.

        If the name matches a CTE, expand the CTE body instead.
        Otherwise look up columns in self.schema.
        """
        table_upper = str(table_name).upper()
        alias_upper = str(alias).upper() if alias else table_upper

        # Track alias → original table name for key-filtering callers.
        if self._alias_to_table is not None:
            self._alias_to_table.setdefault(alias_upper, table_upper)

        # CTE reference → expand inline under the alias
        if table_upper in cte_map:
            sub: dict[str, list] = {}
            self._visit_query(cte_map[table_upper], context, sub, cte_map)
            if context == self.SET:
                result[alias_upper] = []
            else:
                result[alias_upper] = sorted({c for cols in sub.values() for c in cols})
            return

        columns = list(self.schema.get(table_upper, {}).keys()) if context == self.BAG else []
        if columns and self._single_pk_cols is not None:
            pk_remove = self._single_pk_cols.get(table_upper, set())
            columns = [c for c in columns if c not in pk_remove]

        # If the alias was already seen (e.g. self-join), merge column sets
        if alias_upper in result:
            result[alias_upper] = sorted(set(result[alias_upper]) | set(columns))
        else:
            result[alias_upper] = columns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CQ_OUT_OF_SCOPE_RE = [re.compile(p) for p in [
    r"\bNOT\s+IN\b",
    r"\bNOT\s+\w+\s+IN\s*\(",   # NOT <col> IN ( -- same semantics as NOT IN
    r"\bNOT\s+EXISTS\b",
    r"\bGROUP\s+BY\b",
    r"\bHAVING\b",
    r"\bCOUNT\s*\(",
    r"\bSUM\s*\(",
    r"\bAVG\s*\(",
    r"\bMAX\s*\(",
    r"\bMIN\s*\(",
    r"\bUNION\b",
    r"\bINTERSECT\b",
    r"\bEXCEPT\b",
]]


def _is_cq_scoped(sql: str) -> bool:
    """Return True if *sql* is within the CQ scope of the Combined Semantics theory."""
    upper = sql.upper()
    return not any(rx.search(upper) for rx in _CQ_OUT_OF_SCOPE_RE)


def _parse_single_pk_columns(constraints: list) -> dict[str, set]:
    """
    Parse benchmark constraint list into a mapping of table → set of
    single-column primary-key column names.

    Only single-column PK constraints are returned; composite PKs (two or
    more columns in one constraint) are ignored because they do not guarantee
    individual column uniqueness.

    Format of each constraint entry:
        {"primary": [{"value": "TABLE__COLUMN"}, ...]}
    A single-element list → single-column PK.
    A multi-element list  → composite PK (skipped here).
    """
    result: dict[str, set] = {}
    for c in (constraints or []):
        pk_entries = c.get('primary')
        if not pk_entries:
            continue
        if len(pk_entries) != 1:
            continue
        val = pk_entries[0].get('value', '')
        if '__' not in val:
            continue
        table, col = val.split('__', 1)
        result.setdefault(table.upper(), set()).add(col.upper())
    return result


_QUERY_KEYS = frozenset({
    'select', 'select_distinct',
    'union', 'union_all', 'union_distinct',
    'intersect', 'intersect_all',
    'except', 'except_all',
})


def _is_query(node: dict) -> bool:
    """Return True if *node* looks like a subquery dict."""
    return isinstance(node, dict) and bool(_QUERY_KEYS & node.keys())


def _ensure_list(val: Any) -> list:
    if val is None:
        return []
    return val if isinstance(val, list) else [val]
