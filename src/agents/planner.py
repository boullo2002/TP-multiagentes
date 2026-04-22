from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import SystemMessage

from llm.client import LLMClient


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


PLANNER_FALLBACK_SYSTEM_PROMPT = """\
Sos un planner NL->SQL de apoyo. Tu salida debe ser JSON valido y nada mas.

Objetivo:
- Mejorar una pre-planificacion heuristica cuando su confianza es baja.
- Usar SOLO entidades/campos que existan en el schema proporcionado.
- Resolver ambiguedad de idioma (es/en) en la pregunta.

Reglas:
- No inventes tablas/columnas.
- Prioriza tablas existentes y relevantes para la pregunta.
- Si no hay suficiente senal, marca needs_clarification=true y redacta una sola pregunta breve.
- Responde solo con JSON que cumpla exactamente este esquema:
{
  "summary": "string",
  "tables": ["string"],
  "assumptions": ["string"],
  "confidence": 0.0,
  "needs_clarification": false,
  "clarification_question": "string"
}
"""


_WORD = re.compile(r"[a-z0-9_]+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_TOP = re.compile(r"\btop\s+(\d{1,4})\b", re.I)
_AGG = re.compile(
    r"\b(count|sum|avg|average|max|min|total|conteo|promedio|media|maximo|minimo)\b", re.I
)
_ORDER = re.compile(r"\b(order|sort|desc|asc|orden|ordenar|mayor|menor)\b", re.I)
_ALIAS_HINT = re.compile(
    r"\b([a-z0-9_]{2,40})\b\s+(?:se\s+refiere\s+a|significa|means?)\s+\b([a-z0-9_]{2,40})\b",
    re.I,
)

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
    "and",
    "the",
    "this",
    "that",
    "for",
    "from",
    "to",
    "of",
    "please",
    "show",
    "give",
    "list",
    "what",
    "which",
    "who",
    "when",
    "where",
    "how",
    "many",
    "much",
}

_SEMANTIC_SYNONYMS = {
    "pelicula": {"film", "movie", "movies", "title"},
    "peliculas": {"film", "movie", "movies", "title"},
    "movie": {"film", "pelicula", "peliculas", "title"},
    "movies": {"film", "pelicula", "peliculas", "title"},
    "cliente": {"customer", "customers"},
    "clientes": {"customer", "customers"},
    "customer": {"cliente", "clientes"},
    "customers": {"cliente", "clientes"},
    "alquiler": {"rental", "rentals"},
    "alquileres": {"rental", "rentals"},
    "rental": {"alquiler", "alquileres", "rentals"},
    "rentals": {"alquiler", "alquileres", "rental"},
    "pago": {"payment", "payments"},
    "pagos": {"payment", "payments"},
    "payment": {"pago", "pagos", "payments"},
    "payments": {"pago", "pagos", "payment"},
    "actor": {"performer", "cast"},
    "actores": {"actor", "performer", "cast"},
    "categoria": {"category", "categories", "genre"},
    "categorias": {"category", "categories", "genre"},
    "city": {"ciudad", "ciudades"},
    "ciudad": {"city", "cities"},
}


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return s.lower()


def _lemma(token: str) -> str:
    t = token.strip().lower()
    if len(t) >= 5 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) >= 4 and t.endswith("es"):
        return t[:-2]
    if len(t) >= 4 and t.endswith("s"):
        return t[:-1]
    return t


def _tokens(text: str) -> set[str]:
    raw = _WORD.findall(_norm(text))
    base = {t for t in raw if len(t) >= 2 and t not in _STOPWORDS}
    out = set(base)
    out.update({_lemma(t) for t in base})
    for t in list(base):
        out.update(_SEMANTIC_SYNONYMS.get(t, set()))
    return {t for t in out if len(t) >= 2 and t not in _STOPWORDS}


def _extract_semantic_aliases(semantic_schema_descriptions: dict[str, Any] | None) -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = {}
    if not isinstance(semantic_schema_descriptions, dict):
        return alias_map

    def _add(src: str, dst: str) -> None:
        s = _lemma(_norm(src))
        d = _lemma(_norm(dst))
        if len(s) < 2 or len(d) < 2 or s == d:
            return
        alias_map.setdefault(s, set()).add(d)

    def _scan_text(text: str) -> None:
        for m in _ALIAS_HINT.finditer(_norm(text or "")):
            _add(m.group(1), m.group(2))

    tables = semantic_schema_descriptions.get("tables")
    if isinstance(tables, list):
        for t in tables:
            if not isinstance(t, dict):
                continue
            _scan_text(str(t.get("description") or ""))
            cols = t.get("columns")
            if isinstance(cols, list):
                for c in cols:
                    if isinstance(c, dict):
                        _scan_text(str(c.get("description") or ""))

    for v in semantic_schema_descriptions.values():
        if isinstance(v, dict):
            desc = v.get("description")
            if isinstance(desc, str):
                _scan_text(desc)
    return alias_map


def _extract_answer_aliases(human_answers: dict[str, Any] | None) -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = {}
    if not isinstance(human_answers, dict):
        return alias_map

    def _add(src: str, dst: str) -> None:
        s = _lemma(_norm(src))
        d = _lemma(_norm(dst))
        if len(s) < 2 or len(d) < 2 or s == d:
            return
        alias_map.setdefault(s, set()).add(d)

    def _scan_text(text: str) -> None:
        for m in _ALIAS_HINT.finditer(_norm(text or "")):
            _add(m.group(1), m.group(2))

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            _scan_text(value)
            return
        if isinstance(value, list):
            for item in value:
                _walk(item)
            return
        if isinstance(value, dict):
            for k, v in value.items():
                _walk(str(k))
                _walk(v)

    _walk(human_answers)
    return alias_map


def _expand_question_tokens_with_aliases(
    question_tokens: set[str],
    semantic_schema_descriptions: dict[str, Any] | None,
    human_answers: dict[str, Any] | None = None,
) -> set[str]:
    alias_map = _extract_semantic_aliases(semantic_schema_descriptions)
    answer_alias_map = _extract_answer_aliases(human_answers)
    for k, vals in answer_alias_map.items():
        alias_map.setdefault(k, set()).update(vals)
    if not alias_map:
        return question_tokens
    expanded = set(question_tokens)
    frontier = list(question_tokens)
    seen = set(frontier)
    # BFS acotado para evitar expansiones excesivas.
    hops = 0
    while frontier and hops < 3:
        next_frontier: list[str] = []
        for tok in frontier:
            for nxt in alias_map.get(tok, set()):
                if nxt not in seen:
                    seen.add(nxt)
                    expanded.add(nxt)
                    next_frontier.append(nxt)
                    expanded.update(_SEMANTIC_SYNONYMS.get(nxt, set()))
        frontier = next_frontier
        hops += 1
    return expanded


def _lexical_parts(name: str) -> set[str]:
    parts = {p for p in _norm(name).split("_") if p}
    expanded = set(parts)
    for p in list(parts):
        expanded.add(_lemma(p))
        expanded.update(_SEMANTIC_SYNONYMS.get(p, set()))
    return expanded


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
    semantic_text: str,
    recent_tables: list[str],
) -> int:
    score = 0
    t_name = _norm(table_name)
    t_parts = _lexical_parts(table_name)
    if t_name in question_tokens:
        score += 6
    if _lemma(t_name) in question_tokens:
        score += 4
    score += sum(3 for p in t_parts if p in question_tokens)

    for c in col_names:
        c_norm = _norm(c)
        c_parts = _lexical_parts(c)
        if c_norm in question_tokens:
            score += 2
        if _lemma(c_norm) in question_tokens:
            score += 2
        score += sum(1 for p in c_parts if p in question_tokens)

    sem_tokens = _tokens(semantic_text)
    if sem_tokens:
        overlap = len(question_tokens & sem_tokens)
        score += min(overlap * 2, 8)

    if table_name.lower() in {x.lower() for x in recent_tables}:
        score += 2
    return score


def _semantic_text_for_table(
    table_name: str, semantic_schema_descriptions: dict[str, Any] | None
) -> str:
    if not isinstance(semantic_schema_descriptions, dict):
        return ""
    parts: list[str] = []
    table_name_norm = _norm(table_name)

    # Formato nuevo/persistido: {"tables":[{"name":"...", "description":"...", "columns":[...]}]}
    tables = semantic_schema_descriptions.get("tables")
    if isinstance(tables, list):
        for t in tables:
            if not isinstance(t, dict):
                continue
            t_name = str(t.get("name") or "").strip()
            if _norm(t_name) != table_name_norm:
                continue
            desc = t.get("description")
            if isinstance(desc, str):
                parts.append(desc)
            cols = t.get("columns")
            if isinstance(cols, list):
                for c in cols:
                    if not isinstance(c, dict):
                        continue
                    c_name = str(c.get("name") or "").strip()
                    if c_name:
                        parts.append(c_name)
                    c_desc = c.get("description")
                    if isinstance(c_desc, str):
                        parts.append(c_desc)

    # Formato legacy: {"film": {"description":"...", "columns":{"title":"..."}}}
    table_block = semantic_schema_descriptions.get(table_name)
    if isinstance(table_block, dict):
        description = table_block.get("description")
        if isinstance(description, str):
            parts.append(description)
        columns = table_block.get("columns")
        if isinstance(columns, dict):
            for col, col_desc in columns.items():
                parts.append(str(col))
                if isinstance(col_desc, str):
                    parts.append(col_desc)
    return " ".join(parts).strip()


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
    schema_table_count: int,
    token_count: int,
) -> tuple[float, bool, str]:
    # Heuristica simple y deterministica:
    # - Poca evidencia semantica + sin tablas candidatas => pedir aclaracion.
    raw = 0.20 + min(best_score / 12.0, 0.60) + (0.20 if table_count > 0 else 0.0)
    confidence = max(0.0, min(round(raw, 2), 1.0))
    low_signal = best_score <= 1 and table_count == 0 and token_count >= 2
    # Si hay catálogo cargado, dejamos avanzar al Query Agent: puede resolver por
    # contexto semántico aunque falle el match léxico del planner heurístico.
    no_schema_available = schema_table_count == 0
    needs = (low_signal or confidence < 0.40) and no_schema_available
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
    semantic_schema_descriptions: dict[str, Any] | None = None,
    human_answers: dict[str, Any] | None = None,
    short_term: dict[str, Any] | None = None,
    language: str = "es",
) -> QueryPlan:
    """Planner heurístico con señales reales de schema + contexto reciente."""
    q = user_question or ""
    q_tokens = _tokens(q)
    q_tokens = _expand_question_tokens_with_aliases(
        q_tokens,
        semantic_schema_descriptions,
        human_answers,
    )
    st = short_term if isinstance(short_term, dict) else {}
    recent_tables = [str(x) for x in (st.get("recent_tables") or []) if str(x).strip()]

    all_tables = _schema_tables(schema_catalog)
    candidates: list[tuple[int, str]] = []
    for t in all_tables:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        cols = t.get("columns") if isinstance(t.get("columns"), list) else []
        col_names = [str(c.get("name") or "") for c in cols if isinstance(c, dict)]
        score = _table_score(
            question_tokens=q_tokens,
            table_name=name,
            col_names=col_names,
            semantic_text=_semantic_text_for_table(name, semantic_schema_descriptions),
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
        schema_table_count=len(all_tables),
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


def maybe_refine_plan_with_llm(
    *,
    plan: QueryPlan,
    user_question: str,
    schema_catalog: dict[str, Any] | None,
    semantic_schema_descriptions: dict[str, Any] | None,
    language: str,
    enabled: bool,
    confidence_threshold: float,
) -> QueryPlan:
    """Refina planner heuristico con LLM cuando la señal es baja.

    Guardrails:
    - Solo corre si enabled=True y confidence<threshold.
    - Si el LLM falla o responde invalido, devuelve plan original.
    - Nunca usa tablas fuera del catalogo real.
    """
    if not enabled or plan.confidence >= confidence_threshold:
        return plan

    allowed_tables: set[str] = set()
    for t in _schema_tables(schema_catalog):
        name = str(t.get("name") or "").strip()
        if name:
            allowed_tables.add(name)

    prompt = (
        f"language={language}\n"
        f"user_question={user_question}\n"
        f"heuristic_plan={plan}\n"
        f"schema_catalog={schema_catalog if isinstance(schema_catalog, dict) else {}}\n"
        "semantic_schema_descriptions="
        f"{semantic_schema_descriptions if isinstance(semantic_schema_descriptions, dict) else {}}\n"
    )
    try:
        msg = (
            LLMClient()
            .get()
            .invoke(
                [SystemMessage(content=PLANNER_FALLBACK_SYSTEM_PROMPT), ("user", prompt)],
                config={
                    "run_name": "PlannerFallback · Heuristic→LLM",
                    "tags": ["agent:planner", "step:fallback_llm", "workflow:nlq"],
                    "metadata": {"agent": "planner", "step": "fallback_llm"},
                },
            )
        )
        raw = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
        # tolera fences ocasionales sin romper.
        raw = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.I | re.M).strip()
        import json

        data = json.loads(raw)
        if not isinstance(data, dict):
            return plan
        refined_tables_raw = data.get("tables")
        if isinstance(refined_tables_raw, list):
            refined_tables = [str(t).strip() for t in refined_tables_raw if str(t).strip()]
        else:
            refined_tables = []
        # Guardrail fuerte: solo tablas reales.
        valid_tables = [t for t in refined_tables if t in allowed_tables]
        final_tables = valid_tables if valid_tables else plan.tables

        assumptions_raw = data.get("assumptions")
        assumptions = (
            [str(a).strip() for a in assumptions_raw if str(a).strip()]
            if isinstance(assumptions_raw, list)
            else plan.assumptions
        )
        confidence_raw = data.get("confidence")
        confidence = (
            float(confidence_raw)
            if isinstance(confidence_raw, int | float)
            else float(plan.confidence)
        )
        confidence = max(0.0, min(round(confidence, 2), 1.0))
        needs_raw = data.get("needs_clarification")
        needs = bool(needs_raw) if isinstance(needs_raw, bool) else plan.needs_clarification
        clarification = str(data.get("clarification_question") or "").strip()
        summary = str(data.get("summary") or "").strip() or plan.summary
        return QueryPlan(
            summary=summary,
            tables=final_tables,
            assumptions=assumptions,
            steps=plan.steps,
            dependencies=plan.dependencies,
            confidence=confidence,
            needs_clarification=needs,
            clarification_question=clarification if needs else "",
        )
    except Exception:
        return plan
