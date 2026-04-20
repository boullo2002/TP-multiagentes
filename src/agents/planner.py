from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryPlan:
    summary: str
    tables: list[str]
    assumptions: list[str]


_WORD = re.compile(r"[a-z0-9_]+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_TOP = re.compile(r"\btop\s+(\d{1,4})\b", re.I)

_STOPWORDS = {
    "a",
    "al",
    "algo",
    "con",
    "cuanto",
    "cuantos",
    "cual",
    "cuales",
    "de",
    "del",
    "el",
    "en",
    "es",
    "fue",
    "hay",
    "la",
    "las",
    "lo",
    "los",
    "mas",
    "me",
    "mostrar",
    "muestra",
    "muestrame",
    "para",
    "por",
    "que",
    "quiero",
    "se",
    "sin",
    "solo",
    "su",
    "sus",
    "un",
    "una",
    "y",
}


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return s.lower()


def _tokens(text: str) -> set[str]:
    raw = _WORD.findall(_norm(text))
    return {t for t in raw if len(t) >= 2 and t not in _STOPWORDS}


def _schema_tables(schema_catalog: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(schema_catalog, dict):
        return []
    tables = schema_catalog.get("tables")
    if isinstance(tables, list):
        return [t for t in tables if isinstance(t, dict)]
    return []


def _table_score(
    *,
    question_tokens: set[str],
    table_name: str,
    col_names: list[str],
    recent_tables: list[str],
) -> int:
    score = 0
    t_name = _norm(table_name)
    t_parts = {p for p in t_name.split("_") if p}
    if t_name in question_tokens:
        score += 6
    score += sum(3 for p in t_parts if p in question_tokens)

    for c in col_names:
        c_norm = _norm(c)
        c_parts = {p for p in c_norm.split("_") if p}
        if c_norm in question_tokens:
            score += 2
        score += sum(1 for p in c_parts if p in question_tokens)

    if table_name.lower() in {x.lower() for x in recent_tables}:
        score += 2
    return score


def build_plan(
    user_question: str,
    *,
    schema_catalog: dict[str, Any] | None = None,
    short_term: dict[str, Any] | None = None,
) -> QueryPlan:
    """Planner heurístico con señales reales de schema + contexto reciente."""
    q = user_question or ""
    q_tokens = _tokens(q)
    st = short_term if isinstance(short_term, dict) else {}
    recent_tables = [str(x) for x in (st.get("recent_tables") or []) if str(x).strip()]

    candidates: list[tuple[int, str]] = []
    for t in _schema_tables(schema_catalog):
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        cols = t.get("columns") if isinstance(t.get("columns"), list) else []
        col_names = [str(c.get("name") or "") for c in cols if isinstance(c, dict)]
        score = _table_score(
            question_tokens=q_tokens,
            table_name=name,
            col_names=col_names,
            recent_tables=recent_tables,
        )
        if score > 0:
            candidates.append((score, name))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    top_tables = [name for _, name in candidates[:6]]

    assumptions: list[str] = []
    years = _YEAR.findall(q)
    if years:
        assumptions.append(
            f"Filtro temporal sugerido por la pregunta: {', '.join(dict.fromkeys(years))}."
        )
    m_top = _TOP.search(q)
    if m_top:
        assumptions.append(f"El usuario pide un ranking top-{m_top.group(1)}.")
    if re.search(r"\bmas vista|mas alquilada|top|ranking\b", _norm(q)):
        assumptions.append(
            "Para 'más vista/ranking' se suele usar rentals como proxy de popularidad."
        )
    if not top_tables and recent_tables:
        assumptions.append(
            "Se priorizan tablas recientes de la conversación por falta de match directo."
        )
        top_tables = recent_tables[:4]
    if not top_tables:
        assumptions.append(
            "No se detectaron tablas con alta confianza; puede requerirse aclaración del dominio."
        )

    summary = (
        "Objetivo: identificar tablas candidatas y restricciones antes de generar SQL. "
        f"Tablas priorizadas: {', '.join(top_tables) if top_tables else 'ninguna clara'}."
    )
    return QueryPlan(
        summary=summary,
        tables=top_tables,
        assumptions=assumptions,
    )
