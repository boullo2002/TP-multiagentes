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
    r"\b(film|films|movie|movies|rental|rentals|customer|customers|payment|payments|"
    r"actor|actors|inventory|inventor(y|ies)|store|stores|staff|address|city|cities|"
    r"country|categories|category|language|tabular|table|tables|row|rows|column|sql|query|"
    r"count|sum|avg|max|min|top|total|list|paid|paying|duration|title|titles|amount|"
    r"película|peliculas|pelis|alquiler|alquileres|cliente|clientes|pago|pagos|actores|actor|"
    r"tabla|tablas|inventario|tienda|dvd|"
    r"cuánto|cuánta|cuántas|cuántos|cuanto|cuantos|cuantas|"
    r"how\s+many|which|who|when|where|show|give\s+me|return|years?|year)\b",
    re.I,
)


def _has_data_query_intent(text: str) -> bool:
    return bool(_DATA_QUERY_HINTS.search(text or ""))


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
            "Hi! I answer questions about the DVD rental database (films, rentals, customers, "
            "payments, …).\n\n"
            "Try something like **top 5 most rented films** or **how many customers are there**."
        )
    return (
        "¡Hola! Podés preguntarme sobre la base tipo DVD rental (películas, alquileres, "
        "clientes, pagos, …).\n\n"
        "Probá: **top 5 películas más alquiladas** o **cuántos clientes hay**."
    )


def _language_preference_ack(target: str) -> str:
    if target == "en":
        return (
            "Got it — I'll answer in **English** from now on.\n\n"
            "When you're ready, ask a question about the data (films, rentals, customers, …)."
        )
    return (
        "Listo — a partir de ahora respondo en **español**.\n\n"
        "Cuando quieras, hacé una pregunta sobre los datos (películas, alquileres, clientes, …)."
    )


def _off_topic_nudge(lang: str) -> str:
    if lang == "en":
        return (
            "That doesn't look like a question about this database.\n\n"
            "Ask in plain language about **films**, **rentals**, **customers**, **payments**, "
            "or say **capabilities** to see what I can do."
        )
    return (
        "Eso no parece una consulta sobre los datos de esta base.\n\n"
        "Probá con una pregunta sobre **películas**, **alquileres**, **clientes**, **pagos**, "
        "o decí **capacidades** para ver en qué te puedo ayudar."
    )


def _basic_capabilities_answer(lang: str) -> str:
    if lang == "en":
        return (
            "I can help with natural-language questions about the database, for example:\n\n"
            "- list available tables and fields,\n"
            "- answer metrics (counts, averages, top-N, trends),\n"
            "- filter by dates/categories/customers,\n"
            "- explain the SQL I ran and show a preview of results,\n"
            "- refine a query step by step (\"only 2005\", \"order desc\", etc.).\n\n"
            "We can start with **\"what tables are there\"** or a concrete business question."
        )
    return (
        "Puedo ayudarte con consultas en lenguaje natural sobre la base, por ejemplo:\n\n"
        "- listar tablas y campos disponibles,\n"
        "- responder métricas (conteos, promedios, top-N, tendencias),\n"
        "- filtrar por fechas/categorías/clientes,\n"
        "- explicar qué SQL ejecuté y mostrar preview de resultados,\n"
        "- refinar una consulta en pasos (\"ahora solo 2005\", \"ordená desc\", etc.).\n\n"
        "Si querés, arrancamos por: **\"qué tablas hay\"** o una pregunta de negocio concreta."
    )


def query_basic_intents(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_basic_intents")
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
        _add_event(state, "intent_data_query")
        return state
    finally:
        _record_node_latency(state, "query_basic_intents", started)


def router_node(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_router")
    try:
        state["mode"] = "query"
        return state
    finally:
        _record_node_latency(state, "query_router", started)


def query_load_context(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_load_context")
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
        _record_node_latency(state, "query_load_context", started)


def query_planner(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_planner")
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
        _record_node_latency(state, "query_planner", started)


def query_sql_executor(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_sql")
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
        _record_node_latency(state, "query_sql", started)


def query_validator_node(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_validator")
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
        _record_node_latency(state, "query_validator", started)


def query_execute(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_execute")
    try:
        sql_to_run = state.get("sql_draft", "")
        state["sql_validated"] = sql_to_run
        state.pop("last_error", None)
        try:
            state["query_result"] = sql_execute_readonly(sql=sql_to_run, timeout_ms=60_000)
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
        _record_node_latency(state, "query_execute", started)


def query_explain(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_explain")
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
        preview_limit = 10
        table_md = _as_markdown_table(cols, rows, limit=preview_limit, lang=lang)

        if lang == "en":
            content = (
                "### SQL executed\n"
                "```sql\n"
                f"{sql}\n"
                "```\n\n"
                "### Result\n"
                f"- Columns: `{len(cols)}`\n"
                f"- Rows returned: `{row_count}`\n"
                f"- Execution time: `{execution_ms} ms`\n\n"
                "### Data preview\n"
                f"{table_md}\n\n"
            )
            if len(rows) > preview_limit:
                content += f"_Showing {preview_limit} of {len(rows)} rows in this preview._\n\n"
            if len(rows) == 0:
                content += "_The query returned no rows._\n\n"
            content += _format_assumptions_md(assumptions, lang=lang)
            content += (
                "### Limitations\n"
                "- Results are constrained for safety (read-only, row limits).\n"
                "- If you want, I can refine filters, sorting, or top-N.\n"
            )
        else:
            content = (
                "### SQL ejecutado\n"
                "```sql\n"
                f"{sql}\n"
                "```\n\n"
                "### Resultado\n"
                f"- Columnas: `{len(cols)}`\n"
                f"- Filas devueltas: `{row_count}`\n"
                f"- Tiempo de ejecución: `{execution_ms} ms`\n\n"
                "### Preview de datos\n"
                f"{table_md}\n\n"
            )
            if len(rows) > preview_limit:
                content += (
                    f"_Mostrando {preview_limit} de {len(rows)} filas del preview actual._\n\n"
                )
            if len(rows) == 0:
                content += "_La consulta no devolvió filas._\n\n"
            content += _format_assumptions_md(assumptions, lang=lang)
            content += (
                "### Limitaciones\n"
                "- Resultados acotados por seguridad (solo lectura, limites de filas).\n"
                "- Si queres, puedo refinar filtros, ordenamiento o top-N.\n"
            )
        state["messages"] = state.get("messages", []) + [AIMessage(content=content)]
        return state
    finally:
        _record_node_latency(state, "query_explain", started)


def query_update_short_term_memory(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("query_mem")
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
        _record_node_latency(state, "query_mem", started)


def build_query_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("router", router_node)
    g.add_node("query_load", query_load_context)
    g.add_node("query_basic", query_basic_intents)
    g.add_node("query_plan", query_planner)
    g.add_node("query_sql", query_sql_executor)
    g.add_node("query_validate", query_validator_node)
    g.add_node("query_execute", query_execute)
    g.add_node("query_explain", query_explain)
    g.add_node("query_mem", query_update_short_term_memory)

    g.add_edge(START, "router")
    g.add_edge("router", "query_load")
    g.add_conditional_edges(
        "query_basic",
        route_after_query_validator,
        {"end": END, "execute": "query_plan"},
    )

    g.add_edge("query_load", "query_basic")
    g.add_conditional_edges(
        "query_plan",
        route_after_query_validator,
        {"end": END, "execute": "query_sql", "retry": "query_sql"},
    )
    g.add_edge("query_sql", "query_validate")
    g.add_conditional_edges(
        "query_validate",
        route_after_query_validator,
        {"retry": "query_sql", "end": END, "execute": "query_execute"},
    )
    g.add_edge("query_execute", "query_explain")
    g.add_edge("query_explain", "query_mem")
    g.add_edge("query_mem", END)
    return g


_compiled = None


def get_compiled_query_graph():
    global _compiled
    if _compiled is None:
        settings = get_settings()
        _compiled = build_query_graph().compile()
        logger.info(
            "compiled_graph=query max_iterations=%s sql_retry_max=%s",
            settings.graph.max_iterations,
            settings.query_sql_retry_max,
        )
    return _compiled

