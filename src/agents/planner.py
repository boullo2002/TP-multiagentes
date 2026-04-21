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
    steps: list[str]
    dependencies: list[str]
    confidence: float
    needs_clarification: bool
    clarification_question: str


_WORD = re.compile(r"[a-z0-9_]+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_TOP = re.compile(r"\btop\s+(\d{1,4})\b", re.I)
_AGG = re.compile(r"\b(count|sum|avg|average|max|min|total|conteo|promedio|media|maximo|minimo)\b", re.I)
_ORDER = re.compile(r"\b(order|sort|desc|asc|orden|ordenar|mayor|menor)\b", re.I)

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


def _build_steps(
    *,
    lang: str,
    has_filters: bool,
    has_agg: bool,
    has_order: bool,
    top_n: str | None,
) -> list[str]:
    if lang == "en":
        steps = [
            "Identify candidate tables and join keys from schema/catalog.",
            "Map user constraints to SQL predicates (dates, categories, IDs, etc.).",
            "Build a read-only base SELECT preserving valid joins.",
        ]
        if has_agg:
            steps.append("Apply aggregations/grouping required by the request.")
        if has_filters:
            steps.append("Apply explicit filters found in the question.")
        if has_order:
            steps.append("Apply requested sorting direction.")
        if top_n:
            steps.append(f"Apply top-{top_n} limit as requested.")
        steps.append("Enforce safe output limit if no explicit full result was requested.")
        return steps

    steps = [
        "Identificar tablas candidatas y claves de join desde schema/catalog.",
        "Mapear restricciones del usuario a predicados SQL (fechas, categorías, claves, etc.).",
        "Construir un SELECT base de solo lectura con joins validos.",
    ]
    if has_agg:
        steps.append("Aplicar agregaciones/group by si la pregunta lo requiere.")
    if has_filters:
        steps.append("Aplicar filtros explicitos detectados en la pregunta.")
    if has_order:
        steps.append("Aplicar ordenamiento segun direccion solicitada.")
    if top_n:
        steps.append(f"Aplicar limite top-{top_n} pedido por el usuario.")
    steps.append("Forzar limite seguro de salida si no se pidio resultado completo.")
    return steps


def _confidence_and_clarification(
    *,
    lang: str,
    best_score: int,
    table_count: int,
    token_count: int,
) -> tuple[float, bool, str]:
    # Heuristica simple y deterministica:
    # - Poca evidencia semantica + sin tablas candidatas => pedir aclaracion.
    raw = 0.20 + min(best_score / 12.0, 0.60) + (0.20 if table_count > 0 else 0.0)
    confidence = max(0.0, min(round(raw, 2), 1.0))
    low_signal = best_score <= 1 and table_count == 0 and token_count >= 2
    needs = low_signal or confidence < 0.40
    if lang == "en":
        q = (
            "Could you clarify the business metric and the main tables or entities involved?"
            if needs
            else ""
        )
    else:
        q = (
            "¿Podés aclarar la métrica de negocio y las tablas o entidades principales?"
            if needs
            else ""
        )
    return confidence, needs, q


def build_plan(
    user_question: str,
    *,
    schema_catalog: dict[str, Any] | None = None,
    short_term: dict[str, Any] | None = None,
    language: str = "es",
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
    best_score = candidates[0][0] if candidates else 0

    assumptions: list[str] = []
    lang = "en" if str(language).lower() == "en" else "es"
    years = _YEAR.findall(q)
    if years:
        if lang == "en":
            assumptions.append(
                f"Time filter suggested by the question: {', '.join(dict.fromkeys(years))}."
            )
        else:
            assumptions.append(
                f"Filtro temporal sugerido por la pregunta: {', '.join(dict.fromkeys(years))}."
            )
    m_top = _TOP.search(q)
    if m_top:
        if lang == "en":
            assumptions.append(f"The user asked for a top-{m_top.group(1)} ranking.")
        else:
            assumptions.append(f"El usuario pide un ranking top-{m_top.group(1)}.")
    if re.search(r"\bmas vista|mas alquilada|top|ranking|popularity|popularidad\b", _norm(q)):
        if lang == "en":
            assumptions.append(
                "Ranking/popularity: pick a countable metric that exists in the approved schema "
                "(e.g. fact/event rows), not an invented table."
            )
        else:
            assumptions.append(
                "Ranking/popularidad: elegí una métrica contable que exista en el schema aprobado "
                "(p. ej. hechos/eventos), sin inventar tablas."
            )
    if not top_tables and recent_tables:
        if lang == "en":
            assumptions.append(
                "Recent tables from the conversation were prioritized due to missing direct matches."
            )
        else:
            assumptions.append(
                "Se priorizan tablas recientes de la conversación por falta de match directo."
            )
        top_tables = recent_tables[:4]
    if not top_tables:
        if lang == "en":
            assumptions.append(
                "No high-confidence tables were detected; domain clarification may be needed."
            )
        else:
            assumptions.append(
                "No se detectaron tablas con alta confianza; puede requerirse aclaración del dominio."
            )

    has_filters = bool(_YEAR.search(q))
    has_agg = bool(_AGG.search(_norm(q)))
    has_order = bool(_ORDER.search(_norm(q)))
    top_n = m_top.group(1) if m_top else None
    steps = _build_steps(
        lang=lang,
        has_filters=has_filters,
        has_agg=has_agg,
        has_order=has_order,
        top_n=top_n,
    )
    dependencies = [
        "step_2 depends_on step_1",
        "step_3 depends_on step_2",
    ]
    confidence, needs_clarification, clarification_question = _confidence_and_clarification(
        lang=lang,
        best_score=best_score,
        table_count=len(top_tables),
        token_count=len(q_tokens),
    )

    if lang == "en":
        summary = (
            "Goal: identify candidate tables and constraints before generating SQL. "
            f"Prioritized tables: {', '.join(top_tables) if top_tables else 'none clearly identified'}. "
            f"Confidence: {confidence:.2f}."
        )
    else:
        summary = (
            "Objetivo: identificar tablas candidatas y restricciones antes de generar SQL. "
            f"Tablas priorizadas: {', '.join(top_tables) if top_tables else 'ninguna clara'}. "
            f"Confianza: {confidence:.2f}."
        )
    return QueryPlan(
        summary=summary,
        tables=top_tables,
        assumptions=assumptions,
        steps=steps,
        dependencies=dependencies,
        confidence=confidence,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
    )
