from __future__ import annotations

import logging
import re
from dataclasses import asdict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from agents.planner import build_plan
from agents.query_agent import QueryAgent
from agents.validator import validate_sql_draft
from config.settings import get_settings
from graph.checkpoints import new_checkpoint_id
from graph.edges import (
    is_approve_reply,
    route_after_query_hitl_resume,
    route_after_query_validator,
)
from graph.state import GraphState
from memory.persistent_store import PersistentStore
from memory.schema_context_store import SchemaContextStore
from memory.session_store import get_session_store
from memory.short_term import build_short_term_update
from memory.user_preferences import normalize_user_preferences
from services.schema_context_service import compute_schema_hash, run_schema_context_generation
from tools.mcp_client import MCPClientError
from tools.mcp_schema_tool import schema_inspect
from tools.mcp_sql_tool import sql_execute_readonly

logger = logging.getLogger(__name__)


def _log_node(name: str) -> None:
    logger.info("graph_node=%s", name)


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


def _prior_assistant(msgs: list) -> AIMessage | None:
    if len(msgs) < 2:
        return None
    for m in reversed(msgs[:-1]):
        if isinstance(m, AIMessage):
            return m
    return None


def _extract_sql_block(content: str) -> str:
    marker = "SQL:\n"
    if marker not in content:
        return ""
    rest = content.split(marker, 1)[1].strip()
    for sep in ("\n\nSQL sugerido", "\n\n```sql"):
        if sep in rest:
            rest = rest.split(sep)[0]
    return rest.strip()


def _looks_like_sql_hitl_reply(user_raw: str) -> bool:
    u = user_raw.strip()
    if is_approve_reply(u):
        return True
    ul = u.lower()
    return ul.startswith("select") or ul.startswith("with")


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


def router_node(state: GraphState) -> GraphState:
    _log_node("query_router")
    msgs = state.get("messages", [])
    user_raw = _last_user_text(state)
    prior_ai = _prior_assistant(msgs)

    if prior_ai and prior_ai.content:
        c = prior_ai.content if isinstance(prior_ai.content, str) else str(prior_ai.content)
        if "HITL_KIND=sql_execution" in c and user_raw.strip():
            if _looks_like_sql_hitl_reply(user_raw):
                state["mode"] = "query_hitl_resume"
                return state

    state["mode"] = "query"
    return state


def query_hitl_resume_loader(state: GraphState) -> GraphState:
    _log_node("query_hitl_resume_loader")
    _hydrate_query_context(state)
    msgs = state.get("messages", [])
    prior = _prior_assistant(msgs)
    sql = ""
    if prior and prior.content:
        c = prior.content if isinstance(prior.content, str) else str(prior.content)
        sql = _extract_sql_block(c)
    user = _last_user_text(state).strip()
    if not is_approve_reply(user) and "select" in user.lower():
        sql = re.sub(r"```sql\s*|\s*```", "", user, flags=re.I).strip()
    state["sql_draft"] = sql
    state["query_hitl_pending"] = False
    return state


def query_load_context(state: GraphState) -> GraphState:
    _log_node("query_load_context")
    _hydrate_query_context(state)

    # Metadata se usa como referencia/verificación (nombres reales).
    if not state.get("schema_metadata"):
        try:
            state["schema_metadata"] = schema_inspect(schema=None, include_views=False)
        except Exception as e:
            logger.warning("query_load_context schema_inspect_optional failed: %s", e)
            state["schema_metadata"] = {}

    ctx = state.get("schema_context") or {}
    metadata = state.get("schema_metadata") or {}
    current_hash = compute_schema_hash(metadata) if metadata else ""
    existing_hash = str(ctx.get("schema_hash") or "") if isinstance(ctx, dict) else ""
    missing_context = not (isinstance(ctx, dict) and (ctx.get("context_markdown") or "").strip())
    schema_changed = bool(current_hash and existing_hash and current_hash != existing_hash)

    if missing_context or schema_changed:
        try:
            out = run_schema_context_generation(force=True, schema_metadata=metadata)
            if out.status == "ready":
                state["schema_context"] = out.context
            else:
                state["messages"] = state.get("messages", []) + [
                    AIMessage(
                        content=(
                            "Detecté que falta (o cambió) el contexto del schema y la regeneración "
                            "automática requiere respuesta humana. "
                            "Abrí `/schema-agent/ui` y completá las preguntas del Schema Agent."
                        )
                    )
                ]
                state["query_hitl_pending"] = False
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
            state["query_hitl_pending"] = False
            return state
    return state


def query_planner(state: GraphState) -> GraphState:
    _log_node("query_planner")
    q = _last_user_text(state)
    plan = build_plan(q)
    state["query_plan"] = asdict(plan)
    return state


def query_sql_executor(state: GraphState) -> GraphState:
    _log_node("query_sql")
    agent = QueryAgent()
    q = _last_user_text(state)
    ctx = state.get("schema_context") or {}
    ctx_md = ctx.get("context_markdown") if isinstance(ctx, dict) else ""
    sql = agent.draft_sql(
        question=q,
        schema_context_markdown=str(ctx_md or ""),
        schema_metadata=state.get("schema_metadata"),
        short_term=state.get("short_term", {}),
        user_preferences=state.get("user_preferences", {}),
    )
    state["sql_draft"] = sql
    return state


def query_validator_node(state: GraphState) -> GraphState:
    _log_node("query_validator")
    sql = state.get("sql_draft", "")
    out = validate_sql_draft(
        sql,
        schema_metadata=state.get("schema_metadata"),
        user_preferences=state.get("user_preferences"),
    )
    state["sql_validation"] = out.as_dict()
    state["query_hitl_pending"] = bool(out.needs_human_approval) or not bool(out.is_safe)
    state.pop("last_error", None)
    if not out.is_safe:
        state["last_error"] = "; ".join(out.issues) if out.issues else "validación_sql"
        state["messages"] = state.get("messages", []) + [
            AIMessage(
                content="No puedo ejecutar ese SQL tal cual. "
                f"Problemas: {out.issues}. "
                "Corregí el SQL, reformulá la pregunta o pedí un subconjunto con LIMIT."
            )
        ]
    return state


def query_hitl_review(state: GraphState) -> GraphState:
    _log_node("query_hitl")
    sql = state.get("sql_draft", "")
    val = state.get("sql_validation") or {}
    suggested = val.get("suggested_sql")
    cid = new_checkpoint_id()
    extra = ""
    if suggested:
        extra = f"\n\nSQL sugerido (auto-fix, p. ej. LIMIT):\n```sql\n{suggested}\n```\n"
    msg = (
        "Antes de ejecutar, necesito aprobación humana (consulta riesgosa o muy amplia).\n\n"
        f"HITL_CHECKPOINT_ID={cid}\n"
        "HITL_KIND=sql_execution\n\n"
        "Respondé con **APPROVE** para ejecutar tal cual, o pegá un SQL corregido "
        "(solo SELECT).\n\n"
        f"SQL:\n{sql}"
        f"{extra}"
    )
    state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
    return state


def query_execute(state: GraphState) -> GraphState:
    _log_node("query_execute")
    user = _last_user_text(state).strip()
    sql = state.get("sql_draft", "")
    if is_approve_reply(user):
        sql_to_run = sql
    elif user and "select" in user.lower():
        sql_to_run = re.sub(r"```sql\s*|\s*```", "", user, flags=re.I).strip()
    else:
        sql_to_run = sql
    state["sql_validated"] = sql_to_run
    state.pop("last_error", None)
    try:
        state["query_result"] = sql_execute_readonly(sql=sql_to_run, timeout_ms=60_000)
    except MCPClientError as e:
        if e.status_code == 400:
            detail = _mcp_client_detail(e)
            state["last_error"] = detail[:500]
            friendly = (
                "No se pudo ejecutar la consulta SQL (solo lectura). "
                f"Detalle reportado por la base: {detail}"
            )
            state["query_result"] = {"error": True, "detail": detail}
            state["messages"] = state.get("messages", []) + [AIMessage(content=friendly)]
        else:
            raise
    state["query_hitl_pending"] = False
    return state


def query_explain(state: GraphState) -> GraphState:
    _log_node("query_explain")
    res = state.get("query_result", {})
    if res.get("error"):
        return state
    sql = state.get("sql_validated", state.get("sql_draft", ""))
    plan = state.get("query_plan", {})
    assumptions = []
    if isinstance(plan, dict):
        assumptions = plan.get("assumptions") or []
    content = (
        "SQL generado/ejecutado:\n"
        "```sql\n"
        f"{sql}\n"
        "```\n\n"
        f"Preview (hasta {len(res.get('rows', []) or [])} filas):\n"
        f"{res}\n\n"
    )
    if assumptions:
        content += f"Supuestos del plan: {assumptions}\n\n"
    content += (
        "Limitaciones: resultados acotados por seguridad (solo lectura, límites). "
        "Si querés, puedo refinar filtros o el top-N."
    )
    state["messages"] = state.get("messages", []) + [AIMessage(content=content)]
    return state


def query_update_short_term_memory(state: GraphState) -> GraphState:
    _log_node("query_mem")
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
    return state


def build_query_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("router", router_node)
    g.add_node("query_hitl_resume_loader", query_hitl_resume_loader)
    g.add_node("query_load", query_load_context)
    g.add_node("query_plan", query_planner)
    g.add_node("query_sql", query_sql_executor)
    g.add_node("query_validate", query_validator_node)
    g.add_node("query_hitl", query_hitl_review)
    g.add_node("query_execute", query_execute)
    g.add_node("query_explain", query_explain)
    g.add_node("query_mem", query_update_short_term_memory)

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        lambda s: "hitl_resume" if s.get("mode") == "query_hitl_resume" else "query",
        {"hitl_resume": "query_hitl_resume_loader", "query": "query_load"},
    )

    g.add_conditional_edges(
        "query_hitl_resume_loader",
        route_after_query_hitl_resume,
        {"execute": "query_execute", "validate": "query_validate"},
    )

    g.add_edge("query_load", "query_plan")
    g.add_edge("query_plan", "query_sql")
    g.add_edge("query_sql", "query_validate")
    g.add_conditional_edges(
        "query_validate",
        route_after_query_validator,
        {"hitl": "query_hitl", "execute": "query_execute"},
    )
    g.add_edge("query_hitl", END)
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
        logger.info("compiled_graph=query max_iterations=%s", settings.graph.max_iterations)
    return _compiled

