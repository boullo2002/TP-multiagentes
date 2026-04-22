from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import asdict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from agents.planner import build_plan
from agents.query_agent import QueryAgent
from agents.validator import validate_sql_draft
from config.settings import get_settings
from graph.edges import route_after_query_validator
from graph.state import GraphState
from memory.persistent_store import PersistentStore
from memory.schema_context_store import SchemaContextStore
from memory.session_store import get_session_store
from memory.short_term import build_short_term_update
from memory.user_preferences import (
    effective_response_language,
    merge_and_save_user_preferences,
    normalize_user_preferences,
    user_requested_full_sql_result,
)
from services.schema_context_service import run_schema_context_generation
from tools.mcp_client import MCPClientError
from tools.mcp_sql_tool import sql_execute_readonly

logger = logging.getLogger(__name__)


def _log_node(name: str) -> None:
    logger.info("graph_node=%s", name)


def _traj(state: GraphState) -> dict:
    t = state.get("trajectory")
    if not isinstance(t, dict):
        t = {}
        state["trajectory"] = t
    t.setdefault("node_latency_ms", {})
    t.setdefault("events", [])
    t.setdefault("retries", 0)
    t.setdefault("security_blocks", 0)
    t.setdefault("llm_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    return t


def _record_node_latency(state: GraphState, node: str, started_at: float) -> None:
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    _traj(state)["node_latency_ms"][node] = elapsed_ms


def _add_event(state: GraphState, event: str, **extra: object) -> None:
    item = {"event": event, **extra}
    _traj(state)["events"].append(item)


def _mcp_client_detail(e: MCPClientError) -> str:
    d = e.detail
    if isinstance(d, dict):
        inner = d.get("detail", d)
        if isinstance(inner, dict):
            return str(inner.get("message", inner))[:2000]
        return str(inner)[:2000]
    return str(e)[:2000]


def _last_user_text(state: GraphState) -> str:
    msgs = state.get("messages", [])
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""


def _ui_lang(state: GraphState) -> str:
    return effective_response_language(state.get("user_preferences", {}), _last_user_text(state))


def _as_markdown_table(
    columns: list[str], rows: list[list], limit: int = 10, *, lang: str = "es"
) -> str:
    empty_cols = "_No columns to display._" if lang == "en" else "_Sin columnas para mostrar._"
    empty_rows = "_No rows._" if lang == "en" else "_Sin filas._"
    if not columns:
        return empty_cols
    view = rows[:limit]
    header = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join([" --- " for _ in columns]) + "|"
    body_lines: list[str] = []
    for r in view:
        vals = [str(v).replace("\n", " ") if v is not None else "NULL" for v in r]
        body_lines.append("| " + " | ".join(vals) + " |")
    if not body_lines:
        return empty_rows
    return "\n".join([header, sep, *body_lines])


def _format_assumptions_md(assumptions: list[str], *, lang: str) -> str:
    if not assumptions:
        return ""
    title = "### Interpretation" if lang == "en" else "### Interpretacion"
    lines = [f"- {str(a).strip()}" for a in assumptions if str(a).strip()]
    if not lines:
        return ""
    return f"{title}\n" + "\n".join(lines) + "\n\n"


def _hydrate_query_context(state: GraphState) -> None:
    settings = get_settings()
    prefs_store = PersistentStore(f"{settings.storage.data_dir}/user_preferences.json")
    state["user_preferences"] = normalize_user_preferences(prefs_store.load() or {})

    ctx_store = SchemaContextStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_context.json")
    )
    state["schema_context"] = ctx_store.load() or {}

    state.setdefault("short_term", {})
    sid = state.get("session_id") or "default"
    prev_st = get_session_store().get(sid).get("short_term", {})
    if prev_st:
        base = state["short_term"]
        state["short_term"] = {**prev_st, **base}


def _is_capabilities_question(text: str) -> bool:
    t = text.lower().strip()
    if t in {"capacidades", "capacidad", "capabilities", "capability"}:
        return True
    return any(
        p in t
        for p in (
            "qué podés hacer",
            "que podes hacer",
            "qué puedes hacer",
            "que puedes hacer",
            "cuáles son tus capacidades",
            "cuales son tus capacidades",
            "cómo te uso",
            "como te uso",
            "en qué me podés ayudar",
            "en que me podes ayudar",
        )
    )


def _is_tables_inventory_question(text: str) -> bool:
    t = text.lower()
    return any(
        p in t
        for p in (
            "qué tablas hay",
            "que tablas hay",
            "cuáles son las tablas",
            "cuales son las tablas",
            "listado de tablas",
            "listar tablas",
            "mostrar tablas",
            "nombres de las tablas",
        )
    )


_DATA_QUERY_HINTS = re.compile(
    r"\b(select|from|join|where|having|group|sql|query|queries|database|data|tabular|"
    r"table|tables|row|rows|column|columns|schema|count|sum|avg|average|max|min|top|total|"
    r"list|ranking|filters?|order|sort|aggregate|record|records|metric|metrics|report|trend|"
    r"results?|preview|uuid|status|created|updated|timestamp|"
    r"customer|customers|user|users|order|orders|product|products|payment|payments|"
    r"transaction|transactions|invoice|invoices|account|accounts|event|events|"
    r"item|items|category|categories|city|cities|country|address|amount|title|titles|"
    r"duration|paid|paying|"
    r"datos|tabla|tablas|registros|filas|columnas|consulta|consultas|cliente|clientes|"
    r"pago|pagos|métricas|metricas|"
    r"cuánto|cuánta|cuántas|cuántos|cuanto|cuantos|cuantas|"
    r"listado|mostrar|dame|cuales|cual|como|quién|quien|cuándo|cuando|dónde|donde|"
    r"how\s+many|which|who|when|where|show|give\s+me|return|years?|year)\b",
    re.I,
)


def _has_data_query_intent(text: str) -> bool:
    return bool(_DATA_QUERY_HINTS.search(text or ""))


_TOKEN_WORDS = re.compile(r"[a-z0-9_]+")
_FOLLOWUP_REFINEMENT = re.compile(
    r"\b(top\s*\d+|ahora|solo|ordena|ordenar|desc|asc|mismo|misma|esas?|estos?)\b", re.I
)
_DOMAIN_TERMS = frozenset(
    {
        "film",
        "pelicula",
        "peliculas",
        "peli",
        "pelis",
        "actor",
        "actores",
        "categoria",
        "categorias",
        "category",
        "categories",
        "customer",
        "customers",
        "cliente",
        "clientes",
        "city",
        "cities",
        "ciudad",
        "ciudades",
        "payment",
        "payments",
        "pago",
        "pagos",
        "rental",
        "rentals",
        "alquiler",
        "alquileres",
        "inventory",
        "address",
        "country",
    }
)
_NOISE_TERMS = frozenset(
    {
        "dame",
        "mostrar",
        "mostrame",
        "quiero",
        "las",
        "los",
        "la",
        "el",
        "de",
        "del",
        "que",
        "mas",
        "top",
        "ahora",
        "solo",
    }
)


def _query_words(text: str) -> set[str]:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = {w for w in _TOKEN_WORDS.findall(s.lower()) if len(w) >= 2}
    return {w for w in words if w not in _NOISE_TERMS}


def _schema_anchor_words(state: GraphState) -> set[str]:
    ctx = state.get("schema_context") or {}
    out: set[str] = set()
    if isinstance(ctx, dict):
        table_names = ctx.get("table_names")
        if isinstance(table_names, list):
            for n in table_names:
                out.update(_query_words(str(n)))
        schema_catalog = ctx.get("schema_catalog")
        if isinstance(schema_catalog, dict):
            tables = schema_catalog.get("tables")
            if isinstance(tables, list):
                for t in tables:
                    if not isinstance(t, dict):
                        continue
                    out.update(_query_words(str(t.get("name") or "")))
                    cols = t.get("columns")
                    if isinstance(cols, list):
                        for c in cols:
                            if isinstance(c, dict):
                                out.update(_query_words(str(c.get("name") or "")))
    short_term = state.get("short_term") or {}
    if isinstance(short_term, dict):
        recent_tables = short_term.get("recent_tables")
        if isinstance(recent_tables, list):
            for t in recent_tables:
                out.update(_query_words(str(t)))
    out.update(_DOMAIN_TERMS)
    return out


def _is_non_informative_query(text: str) -> bool:
    key = _normalize_chitchat_key(text)
    if not key:
        return True
    words = _query_words(text)
    return len(words) == 0


def _has_domain_anchor(state: GraphState, text: str) -> bool:
    words = _query_words(text)
    if not words:
        return False
    anchors = _schema_anchor_words(state)
    return bool(words & anchors)


def _is_followup_refinement_query(text: str) -> bool:
    return bool(_FOLLOWUP_REFINEMENT.search(text or ""))


def _language_instruction_target(text: str) -> str | None:
    t = (text or "").lower()
    en_pat = re.compile(
        r"\b(answer|respond|reply|speak|write|use)\b[\s\S]{0,48}\benglish\b|"
        r"\bin\s+english\b|"
        r"\benglish\s+only\b|"
        r"\btalk\s+english\b|"
        r"\bi\s+want\s+you\s+to\s+answer\b[\s\S]{0,24}\benglish\b",
        re.I,
    )
    es_pat = re.compile(
        r"\b(habla|habl(a|á)|responde|contesta)\b[\s\S]{0,36}\b(español|espanol)\b|"
        r"\ben\s+español\b|"
        r"\ben\s+espanol\b|"
        r"\b(in\s+)?spanish\b|"
        r"\banswer\s+in\s+spanish\b",
        re.I,
    )
    if en_pat.search(t):
        return "en"
    if es_pat.search(t):
        return "es"
    return None


def _normalize_chitchat_key(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.lower().strip()).rstrip(".,!?")

_PURE_SOCIAL = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hoi",
        "yo",
        "sup",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "bye",
        "goodbye",
        "ciao",
        "hola",
        "buenos dias",
        "buenas",
        "buenas tardes",
        "buenas noches",
        "gracias",
        "chau",
        "adios",
    }
)
_OFF_TOPIC_STANDALONE = frozenset({"profile", "settings", "config", "configuration"})


def _is_pure_social(text: str) -> bool:
    return _normalize_chitchat_key(text) in _PURE_SOCIAL


def _social_guidance(lang: str) -> str:
    if lang == "en":
        return (
            "Hi! I answer natural-language questions about **your PostgreSQL data** "
            "(the tables documented in the approved schema).\n\n"
            "Try something like **how many rows** are in a table you care about, or "
            "**top N by a count** — use real table and column names from your schema."
        )
    return (
        "¡Hola! Podés preguntarme en lenguaje natural sobre **tus datos en PostgreSQL** "
        "(las tablas del schema documentado).\n\n"
        "Probá **cuántas filas** hay en una tabla que te interese, o un **top N por conteo** "
        "usando nombres reales de tablas y columnas."
    )


def _language_preference_ack(target: str) -> str:
    if target == "en":
        return (
            "Got it — I'll answer in **English** from now on.\n\n"
            "When you're ready, ask anything about the database data."
        )
    return (
        "Listo — a partir de ahora respondo en **español**.\n\n"
        "Cuando quieras, hacé una pregunta sobre los datos de la base."
    )


def _off_topic_nudge(lang: str) -> str:
    if lang == "en":
        return (
            "That doesn't look like a question about this database.\n\n"
            "Ask in plain language about **metrics, filters, tables, or rankings** from your "
            "schema, or say **capabilities** to see what I can do."
        )
    return (
        "Eso no parece una consulta sobre los datos de esta base.\n\n"
        "Probá con una pregunta sobre **métricas, filtros, tablas o rankings** de tu esquema, "
        "o decí **capacidades** para ver en qué te puedo ayudar."
    )


def _domain_clarification_nudge(lang: str) -> str:
    if lang == "en":
        return (
            "I couldn't map that request to entities in the current schema.\n\n"
            "Please mention a database entity (for example: films, actors, rentals, categories, "
            "customers, cities) and the metric you want."
        )
    return (
        "No pude mapear ese pedido a entidades del schema actual.\n\n"
        "Mencioná una entidad de la base (por ejemplo: películas, actores, alquileres, "
        "categorías, clientes, ciudades) y la métrica que querés."
    )


def _basic_capabilities_answer(lang: str) -> str:
    if lang == "en":
        return (
            "I can help with natural-language questions about the database, for example:\n\n"
            "- list available tables and fields,\n"
            "- answer metrics (counts, averages, top-N, trends),\n"
            "- filter by dates, categories, or columns in your schema,\n"
            "- explain the SQL I ran and show a preview of results,\n"
            "- refine a query step by step (\"only 2005\", \"order desc\", etc.).\n\n"
            "We can start with **\"what tables are there\"** or a concrete business question."
        )
    return (
        "Puedo ayudarte con consultas en lenguaje natural sobre la base, por ejemplo:\n\n"
        "- listar tablas y campos disponibles,\n"
        "- responder métricas (conteos, promedios, top-N, tendencias),\n"
        "- filtrar por fechas, categorías o columnas de tu esquema,\n"
        "- explicar qué SQL ejecuté y mostrar preview de resultados,\n"
        "- refinar una consulta en pasos (\"ahora solo 2005\", \"ordená desc\", etc.).\n\n"
        "Si querés, arrancamos por: **\"qué tablas hay\"** o una pregunta de negocio concreta."
    )


def query_basic_intents(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("basic_intents")
    try:
        q = _last_user_text(state).strip()
        if not q:
            return state
        _add_event(state, "intent_received", query=q[:160])

        lang = _ui_lang(state)

        instr = _language_instruction_target(q)
        if instr:
            settings = get_settings()
            merged = merge_and_save_user_preferences(
                settings.storage.data_dir, {"preferred_language": instr}
            )
            state["user_preferences"] = merged
            if not _has_data_query_intent(q):
                state["messages"] = state.get("messages", []) + [
                    AIMessage(content=_language_preference_ack(instr))
                ]
                state["query_blocked"] = True
                _add_event(state, "intent_non_data_blocked", kind="language_preference")
                return state

        if _is_pure_social(q):
            lang = _ui_lang(state)
            state["messages"] = state.get("messages", []) + [
                AIMessage(content=_social_guidance(lang))
            ]
            state["query_blocked"] = True
            _add_event(state, "intent_non_data_blocked", kind="social")
            return state

        if _normalize_chitchat_key(q) in _OFF_TOPIC_STANDALONE:
            lang = _ui_lang(state)
            state["messages"] = state.get("messages", []) + [
                AIMessage(content=_off_topic_nudge(lang))
            ]
            state["query_blocked"] = True
            _add_event(state, "intent_non_data_blocked", kind="off_topic")
            return state

        lang = _ui_lang(state)

        if _is_capabilities_question(q):
            state["messages"] = state.get("messages", []) + [
                AIMessage(content=_basic_capabilities_answer(lang))
            ]
            state["query_blocked"] = True
            _add_event(state, "intent_non_data_blocked", kind="capabilities")
            return state

        if _is_tables_inventory_question(q):
            ctx = state.get("schema_context") or {}
            table_names = ctx.get("table_names") if isinstance(ctx, dict) else None
            names = (
                sorted({str(x) for x in table_names if str(x).strip()})
                if isinstance(table_names, list)
                else []
            )
            if not names:
                msg = (
                    "I couldn't read the table inventory right now. "
                    "Please try again in a few seconds."
                    if lang == "en"
                    else (
                        "No pude leer el inventario de tablas en este momento. "
                        "Probá de nuevo en unos segundos."
                    )
                )
            else:
                preview = ", ".join(names[:50])
                msg = (
                    f"Tables in the public schema ({len(names)}):\n{preview}"
                    if lang == "en"
                    else f"Tablas disponibles en el esquema público ({len(names)}):\n{preview}"
                )
            state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
            state["query_blocked"] = True
            _add_event(state, "intent_non_data_blocked", kind="tables_inventory")
            return state

        if _is_non_informative_query(q) or not _has_data_query_intent(q):
            state["messages"] = state.get("messages", []) + [
                AIMessage(content=_off_topic_nudge(lang))
            ]
            state["query_blocked"] = True
            _add_event(state, "intent_non_data_blocked", kind="non_informative")
            return state

        if not _has_domain_anchor(state, q) and not _is_followup_refinement_query(q):
            state["messages"] = state.get("messages", []) + [
                AIMessage(content=_domain_clarification_nudge(lang))
            ]
            state["query_blocked"] = True
            _add_event(state, "intent_non_data_blocked", kind="domain_unmapped")
            return state
        _add_event(state, "intent_data_query")
        return state
    finally:
        _record_node_latency(state, "basic_intents", started)


def router_node(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("mark_query_mode")
    try:
        state["mode"] = "query"
        return state
    finally:
        _record_node_latency(state, "mark_query_mode", started)


def query_load_context(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("load_context")
    try:
        _hydrate_query_context(state)
        ctx = state.get("schema_context") or {}
        missing_context = not (
            isinstance(ctx, dict) and (ctx.get("context_markdown") or "").strip()
        )

        if missing_context:
            try:
                out = run_schema_context_generation(force=False, trace=False)
                if out.status == "ready":
                    state["schema_context"] = out.context
                else:
                    state["messages"] = state.get("messages", []) + [
                        AIMessage(
                            content=(
                                "Detecté que falta (o cambió) el contexto del schema "
                                "y la regeneración "
                                "automática requiere respuesta humana. "
                                "Abrí `/schema-agent/ui` y completá las preguntas del Schema Agent."
                            )
                        )
                    ]
                    state["query_blocked"] = True
                    return state
            except Exception as e:
                logger.warning("query_load_context auto schema generation failed: %s", e)
                state["messages"] = state.get("messages", []) + [
                    AIMessage(
                        content=(
                            "No pude generar automáticamente el contexto del schema. "
                            "Abrí `/schema-agent/ui` para regenerarlo manualmente."
                        )
                    )
                ]
                state["query_blocked"] = True
                return state
        state["query_retry_count"] = 0
        state["query_retry_pending"] = False
        state["query_retry_issues"] = []
        state["query_same_sql_count"] = 0
        state["query_sql_history"] = []
        state["query_blocked"] = False
        return state
    finally:
        _record_node_latency(state, "load_context", started)


def query_planner(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("planner")
    try:
        q = _last_user_text(state)
        ctx = state.get("schema_context") or {}
        schema_catalog = ctx.get("schema_catalog") if isinstance(ctx, dict) else {}
        plan = build_plan(
            q,
            schema_catalog=schema_catalog if isinstance(schema_catalog, dict) else {},
            short_term=state.get("short_term", {}),
            language=_ui_lang(state),
        )
        plan_dict = asdict(plan)
        state["query_plan"] = plan_dict
        if bool(plan_dict.get("needs_clarification")):
            lang = _ui_lang(state)
            q = str(plan_dict.get("clarification_question") or "").strip()
            if not q:
                q = (
                    "Could you clarify what metric and main entity you need?"
                    if lang == "en"
                    else "¿Podés aclarar qué métrica y entidad principal necesitás?"
                )
            header = (
                "I need a short clarification before drafting SQL:\n\n"
                if lang == "en"
                else "Necesito una aclaración breve antes de generar SQL:\n\n"
            )
            state["messages"] = state.get("messages", []) + [AIMessage(content=f"{header}{q}")]
            state["query_blocked"] = True
            _add_event(state, "planner_requested_clarification")
        return state
    finally:
        _record_node_latency(state, "planner", started)


def query_sql_executor(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("draft_sql_llm")
    try:
        agent = QueryAgent()
        q = _last_user_text(state)
        ctx = state.get("schema_context") or {}
        ctx_md = ctx.get("context_markdown") if isinstance(ctx, dict) else ""
        ctx_catalog = ctx.get("schema_catalog") if isinstance(ctx, dict) else {}
        sem_desc = ctx.get("semantic_descriptions") if isinstance(ctx, dict) else {}
        retry_feedback = ""
        retry_issues = state.get("query_retry_issues") or []
        retry_count = int(state.get("query_retry_count") or 0)
        if retry_issues:
            retry_feedback = (
                f"Intento previo #{retry_count} falló con: "
                + "; ".join(str(i) for i in retry_issues[:5])
            )
        draft = agent.draft_sql(
            question=q,
            query_plan=state.get("query_plan") if isinstance(state.get("query_plan"), dict) else {},
            schema_context_markdown=str(ctx_md or ""),
            schema_catalog=ctx_catalog if isinstance(ctx_catalog, dict) else {},
            semantic_schema_descriptions=sem_desc if isinstance(sem_desc, dict) else {},
            short_term=state.get("short_term", {}),
            retry_feedback=retry_feedback,
            user_preferences=state.get("user_preferences", {}),
        )
        draft_sql = draft.sql if hasattr(draft, "sql") else str(draft)
        state["sql_draft"] = draft_sql
        usage = _traj(state)["llm_usage"]
        draft_usage = draft.usage if hasattr(draft, "usage") else {}
        for k, v in draft_usage.items():
            usage[k] = int(usage.get(k, 0)) + int(v)
        prev = state.get("query_sql_history") or []
        history = [str(x) for x in prev if str(x).strip()]
        history.append(draft_sql.strip())
        state["query_sql_history"] = history[-6:]
        if len(history) >= 2 and history[-1] == history[-2]:
            state["query_same_sql_count"] = int(state.get("query_same_sql_count") or 0) + 1
        else:
            state["query_same_sql_count"] = 0
        return state
    finally:
        _record_node_latency(state, "draft_sql_llm", started)


def query_validator_node(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("validate_sql")
    try:
        sql_raw = state.get("sql_draft") or ""
        sql = sql_raw.strip()
        same_sql_count = int(state.get("query_same_sql_count") or 0)
        if same_sql_count >= 2:
            logger.warning("query_validator retry_loop_detected same_sql_count=%s", same_sql_count)
            lang = _ui_lang(state)
            msg = (
                "I stopped the automatic retries because the same SQL kept being generated. "
                "Please rephrase the request and I will try again."
                if lang == "en"
                else (
                    "Corté los reintentos automáticos porque se repitió la misma SQL varias veces. "
                    "Reformulá la consulta y vuelvo a intentar."
                )
            )
            state["query_retry_pending"] = False
            state["query_blocked"] = True
            state["last_error"] = "retry_loop_detected"
            state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
            _traj(state)["security_blocks"] = int(_traj(state)["security_blocks"]) + 1
            _add_event(state, "retry_loop_blocked")
            return state
        # El modelo pidió aclaración en NL: no es SQL, no reintentar en bucle.
        if sql.upper().startswith("CLARIFY:"):
            lang = _ui_lang(state)
            body = sql[8:].strip() if len(sql) > 8 else ""
            default_clarify = (
                "Could you be a bit more specific about what you need?"
                if lang == "en"
                else "¿Podés precisar un poco más qué necesitás?"
            )
            clarify_text = body if body else default_clarify
            header = (
                "I need a short clarification to continue (no SQL or special commands needed):\n\n"
                if lang == "en"
                else (
                    "Necesito una aclaración para seguir (no hace falta SQL ni comandos "
                    "especiales):\n\n"
                )
            )
            state["sql_validation"] = {
                "is_safe": False,
                "needs_human_approval": False,
                "issues": ["clarify"],
                "suggested_sql": None,
            }
            state["query_retry_pending"] = False
            state["query_blocked"] = True
            state["messages"] = state.get("messages", []) + [
                AIMessage(content=f"{header}{clarify_text}")
            ]
            state.pop("last_error", None)
            _add_event(state, "clarification_requested")
            return state

        out = validate_sql_draft(
            sql_raw,
            schema_metadata=None,
            user_preferences=state.get("user_preferences"),
        )
        # Sin HITL SQL: si hay suggested_sql (ej LIMIT), lo aplicamos automáticamente.
        if out.is_safe and out.suggested_sql:
            state["sql_draft"] = out.suggested_sql
            out.suggested_sql = None

        state["sql_validation"] = out.as_dict()
        state["query_retry_pending"] = False
        state["query_blocked"] = not bool(out.is_safe)
        state.pop("last_error", None)
        if not out.is_safe:
            state["query_retry_issues"] = list(out.issues or [])
            retry_count = int(state.get("query_retry_count") or 0)
            retry_max = int(get_settings().query_sql_retry_max)
            if retry_count < retry_max:
                state["query_retry_count"] = retry_count + 1
                state["query_retry_pending"] = True
                state["query_blocked"] = False
                _traj(state)["retries"] = int(_traj(state)["retries"]) + 1
                _add_event(state, "sql_retry_scheduled", retry_count=state["query_retry_count"])
                return state

            state["last_error"] = "; ".join(out.issues) if out.issues else "validación_sql"
            lang = _ui_lang(state)
            fail_body = (
                "I couldn't run the query after several automatic attempts. "
                f"Issues: {out.issues}. "
                "Please rephrase in natural language and I'll try again."
                if lang == "en"
                else (
                    "No pude ejecutar la consulta después de varios intentos automáticos. "
                    f"Problemas detectados: {out.issues}. "
                    "Reformulá la pregunta en lenguaje natural y vuelvo a intentarlo."
                )
            )
            state["messages"] = state.get("messages", []) + [AIMessage(content=fail_body)]
            _traj(state)["security_blocks"] = int(_traj(state)["security_blocks"]) + 1
            _add_event(state, "sql_validation_blocked", issues=out.issues[:3] if out.issues else [])
        return state
    finally:
        _record_node_latency(state, "validate_sql", started)


def query_execute(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("execute_sql")
    try:
        sql_to_run = state.get("sql_draft", "")
        state["sql_validated"] = sql_to_run
        state.pop("last_error", None)
        try:
            prefs = normalize_user_preferences(state.get("user_preferences"))
            want_full = user_requested_full_sql_result(
                user_text=_last_user_text(state),
                prefs=prefs,
            )
            settings = get_settings()
            if want_full:
                max_rows = int(settings.safety.sql_result_fetch_full_max)
            else:
                max_rows = int(prefs.get("default_limit", settings.safety.default_limit))
            max_rows = max(1, min(max_rows, 10_000))
            state["query_result"] = sql_execute_readonly(
                sql=sql_to_run,
                timeout_ms=60_000,
                result_max_rows=max_rows,
            )
            _add_event(state, "sql_execute_ok", row_count=state["query_result"].get("row_count", 0))
        except MCPClientError as e:
            if e.status_code == 400:
                detail = _mcp_client_detail(e)
                state["last_error"] = detail[:500]
                lang = _ui_lang(state)
                friendly = (
                    "The read-only SQL query could not be executed. "
                    f"Database detail: {detail}"
                    if lang == "en"
                    else (
                        "No se pudo ejecutar la consulta SQL (solo lectura). "
                        f"Detalle reportado por la base: {detail}"
                    )
                )
                state["query_result"] = {"error": True, "detail": detail}
                state["messages"] = state.get("messages", []) + [AIMessage(content=friendly)]
                _add_event(state, "sql_execute_error", detail=detail[:120])
            else:
                raise
        return state
    finally:
        _record_node_latency(state, "execute_sql", started)


def query_explain(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("format_answer")
    try:
        res = state.get("query_result", {})
        if res.get("error"):
            return state
        lang = _ui_lang(state)
        sql = state.get("sql_validated", state.get("sql_draft", ""))
        plan = state.get("query_plan", {})
        assumptions = []
        if isinstance(plan, dict):
            assumptions = plan.get("assumptions") or []
        cols = res.get("columns") or []
        rows = res.get("rows") or []
        row_count = int(res.get("row_count") or len(rows))
        execution_ms = res.get("execution_ms")
        prefs = normalize_user_preferences(state.get("user_preferences"))
        show_full = user_requested_full_sql_result(
            user_text=_last_user_text(state),
            prefs=prefs,
        )
        preview_limit = len(rows) if show_full else 10
        table_md = _as_markdown_table(cols, rows, limit=preview_limit, lang=lang)
        truncated = bool(res.get("truncated"))

        if lang == "en":
            data_title = "### Full result (MCP)\n" if show_full else "### Data preview\n"
            content = (
                "### SQL executed\n"
                "```sql\n"
                f"{sql}\n"
                "```\n\n"
                "### Result\n"
                f"- Columns: `{len(cols)}`\n"
                f"- Rows returned: `{row_count}`\n"
                f"- Execution time: `{execution_ms} ms`\n\n"
                f"{data_title}"
                f"{table_md}\n\n"
            )
            if not show_full and len(rows) > preview_limit:
                content += f"_Showing {preview_limit} of {len(rows)} rows in this preview._\n\n"
            if show_full and truncated:
                cap = res.get("result_max_rows")
                content += (
                    f"_Note: the database may contain more rows; MCP returned up to `{cap}` "
                    "(configure `SQL_RESULT_FETCH_FULL_MAX` to raise this cap)._\n\n"
                )
            if len(rows) == 0:
                content += "_The query returned no rows._\n\n"
            content += _format_assumptions_md(assumptions, lang=lang)
            content += (
                "### Limitations\n"
                "- Results are constrained for safety (read-only, row limits).\n"
                "- Ask for “all rows / no preview / full MCP result” to print every row returned.\n"
                "- If you want, I can refine filters, sorting, or top-N.\n"
            )
        else:
            data_title = "### Datos completos (MCP)\n" if show_full else "### Preview de datos\n"
            content = (
                "### SQL ejecutado\n"
                "```sql\n"
                f"{sql}\n"
                "```\n\n"
                "### Resultado\n"
                f"- Columnas: `{len(cols)}`\n"
                f"- Filas devueltas: `{row_count}`\n"
                f"- Tiempo de ejecución: `{execution_ms} ms`\n\n"
                f"{data_title}"
                f"{table_md}\n\n"
            )
            if not show_full and len(rows) > preview_limit:
                content += (
                    f"_Mostrando {preview_limit} de {len(rows)} filas del preview actual._\n\n"
                )
            if show_full and truncated:
                cap = res.get("result_max_rows")
                content += (
                    f"_Nota: en la base puede haber más filas; el MCP devolvió como máximo `{cap}` "
                    "(subí `SQL_RESULT_FETCH_FULL_MAX` si necesitás un tope mayor)._\n\n"
                )
            if len(rows) == 0:
                content += "_La consulta no devolvió filas._\n\n"
            content += _format_assumptions_md(assumptions, lang=lang)
            content += (
                "### Limitaciones\n"
                "- Resultados acotados por seguridad (solo lectura, limites de filas).\n"
                "- Pedí “todas las filas”, “sin preview” o “directo del MCP” "
                "para tabular todo lo devuelto por el MCP.\n"
                "- Si queres, puedo refinar filtros, ordenamiento o top-N.\n"
            )
        state["messages"] = state.get("messages", []) + [AIMessage(content=content)]
        return state
    finally:
        _record_node_latency(state, "format_answer", started)


def query_update_short_term_memory(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("persist_session")
    try:
        st = build_short_term_update(
            prior_short_term=state.get("short_term", {}),
            last_user_question=_last_user_text(state),
            sql_draft=state.get("sql_draft", ""),
            sql_validated=state.get("sql_validated", ""),
            query_plan=state.get("query_plan"),
            query_result=state.get("query_result"),
        )
        state["short_term"] = st
        sid = state.get("session_id") or "default"
        get_session_store().get(sid)["short_term"] = dict(st)
        has_error = bool((state.get("query_result") or {}).get("error"))
        _add_event(
            state,
            "query_finished",
            success=not has_error and not state.get("query_blocked", False),
        )
        logger.info("trajectory_metrics=%s", _traj(state))
        return state
    finally:
        _record_node_latency(state, "persist_session", started)


def build_query_graph() -> StateGraph:
    g = StateGraph(GraphState)
    # Nombres de nodos pensados para LangSmith (orden del flujo NLQ → SQL → respuesta).
    g.add_node("mark_query_mode", router_node)
    g.add_node("load_context", query_load_context)
    g.add_node("basic_intents", query_basic_intents)
    g.add_node("planner", query_planner)
    g.add_node("draft_sql_llm", query_sql_executor)
    g.add_node("validate_sql", query_validator_node)
    g.add_node("execute_sql", query_execute)
    g.add_node("format_answer", query_explain)
    g.add_node("persist_session", query_update_short_term_memory)

    g.add_edge(START, "mark_query_mode")
    g.add_edge("mark_query_mode", "load_context")
    g.add_conditional_edges(
        "basic_intents",
        route_after_query_validator,
        {"end": END, "execute": "planner"},
    )

    g.add_edge("load_context", "basic_intents")
    g.add_conditional_edges(
        "planner",
        route_after_query_validator,
        {"end": END, "execute": "draft_sql_llm", "retry": "draft_sql_llm"},
    )
    g.add_edge("draft_sql_llm", "validate_sql")
    g.add_conditional_edges(
        "validate_sql",
        route_after_query_validator,
        {"retry": "draft_sql_llm", "end": END, "execute": "execute_sql"},
    )
    g.add_edge("execute_sql", "format_answer")
    g.add_edge("format_answer", "persist_session")
    g.add_edge("persist_session", END)
    return g


_compiled = None


def get_compiled_query_graph():
    global _compiled
    if _compiled is None:
        settings = get_settings()
        _compiled = build_query_graph().compile(name="query_nlq_dvd")
        logger.info(
            "compiled_graph=query max_iterations=%s sql_retry_max=%s",
            settings.graph.max_iterations,
            settings.query_sql_retry_max,
        )
    return _compiled

