from __future__ import annotations

import re
from typing import Any

# Heurística: años en la pregunta o en SQL (spec-memory §3.1 recent_filters)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _extract_table_refs(sql: str) -> list[str]:
    refs: list[str] = []
    for m in re.finditer(
        r"\b(?:FROM|JOIN)\s+(?:ONLY\s+)?(?!\()"
        r'(?:(?P<sch>[a-z_][a-z0-9_]*)\.)?(?P<tbl>"[^"]+"|[a-z_][a-z0-9_]*)',
        sql,
        re.I,
    ):
        raw = m.group("tbl") or ""
        name = raw.strip('"').strip()
        if name and name.lower() not in {
            "lateral",
            "unnest",
            "inner",
            "left",
            "right",
            "full",
            "cross",
            "outer",
            "select",
        }:
            refs.append(name)
    return refs


def _merge_recent(prev: list[str], new: list[str], *, max_items: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in prev + new:
        low = x.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(x)
        if len(out) >= max_items:
            break
    return out


def build_short_term_update(
    *,
    prior_short_term: dict[str, Any],
    last_user_question: str,
    sql_draft: str,
    sql_validated: str,
    query_plan: dict[str, Any] | str | None,
    query_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Actualiza el dict short_term según spec-memory §3."""
    st = dict(prior_short_term)
    st["last_user_question"] = last_user_question
    st["last_sql_draft"] = sql_draft
    st["last_sql_executed"] = sql_validated

    plan_tables: list[str] = []
    assumptions: list[str] = []
    if isinstance(query_plan, dict):
        plan_tables = list(query_plan.get("tables") or [])
        assumptions = list(query_plan.get("assumptions") or [])

    from_sql = _extract_table_refs(sql_validated or sql_draft)
    merged_tables = _merge_recent(st.get("recent_tables", []), plan_tables + from_sql)
    st["recent_tables"] = merged_tables

    y_q = [m.group(0) for m in _YEAR.finditer(last_user_question or "")]
    y_sql = [m.group(0) for m in _YEAR.finditer(sql_validated or sql_draft or "")]
    year_tags = [f"year:{y}" for y in dict.fromkeys(y_q + y_sql)]
    if year_tags:
        prev_f = [x for x in st.get("recent_filters", []) if not str(x).startswith("year:")]
        st["recent_filters"] = (year_tags + prev_f)[:16]
    elif "recent_filters" not in st:
        st["recent_filters"] = []

    st["open_assumptions"] = assumptions
    if "CLARIFY:" in (last_user_question or "").upper():
        st["clarifications_requested"] = True
    elif query_result and not query_result.get("error"):
        st["clarifications_requested"] = False

    if query_result and not query_result.get("error"):
        rows = query_result.get("rows") or []
        cols = query_result.get("columns") or []
        st["last_result_preview"] = {
            "columns": cols[:32],
            "rows": rows[:8],
            "row_count": query_result.get("row_count", len(rows)),
        }
    return st
