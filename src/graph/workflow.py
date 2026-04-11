from __future__ import annotations

import logging
from typing import Literal

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from agents.planner import build_plan
from agents.query_agent import QueryAgent
from agents.schema_agent import SchemaAgent
from agents.validator import validate_sql_draft
from config.settings import get_settings
from graph.checkpoints import new_checkpoint_id
from graph.edges import route_after_query_validator, route_after_schema_hitl, route_from_router
from graph.state import GraphState
from memory.persistent_store import PersistentStore
from memory.schema_descriptions_store import SchemaDescriptionsStore
from tools.mcp_schema_tool import schema_inspect
from tools.mcp_sql_tool import sql_execute_readonly

logger = logging.getLogger(__name__)


def _mcp_http_detail(e: httpx.HTTPStatusError) -> str:
    try:
        j = e.response.json()
        if isinstance(j, dict) and "detail" in j:
            return str(j["detail"])[:2000]
    except Exception:
        pass
    return (e.response.text or str(e))[:2000]


def _last_user_text(state: GraphState) -> str:
    msgs = state.get("messages", [])
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            return m.content
    return ""


def router_node(state: GraphState) -> GraphState:
    text = _last_user_text(state).lower()
    mode: Literal["schema", "query", "clarify"] = "query"
    if any(
        k in text for k in ["schema", "tablas", "columnas", "relaciones", "document", "documentá"]
    ):
        mode = "schema"
    state["mode"] = mode
    logger.info("node=router mode=%s", mode)
    return state


def schema_load_existing_descriptions(state: GraphState) -> GraphState:
    settings = get_settings()
    store = SchemaDescriptionsStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_descriptions.json")
    )
    state["schema_descriptions"] = store.load() or {}
    return state


def schema_inspect_metadata(state: GraphState) -> GraphState:
    try:
        state["schema_metadata"] = schema_inspect(schema=None, include_views=False)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 400:
            detail = _mcp_http_detail(e)
            state["schema_metadata"] = {}
            state["messages"] = state.get("messages", []) + [
                AIMessage(
                    content=(
                        "No se pudo obtener el metadata del schema desde el servicio MCP. "
                        f"Detalle: {detail}"
                    )
                )
            ]
        else:
            raise
    return state


def schema_draft_descriptions(state: GraphState) -> GraphState:
    agent = SchemaAgent()
    draft = agent.draft_descriptions(state.get("schema_metadata", {}))
    state["schema_descriptions_draft"] = draft
    state["schema_hitl_pending"] = True
    cid = new_checkpoint_id()
    msg = (
        "Necesito aprobación humana para guardar descripciones de schema.\n\n"
        f"HITL_CHECKPOINT_ID={cid}\n"
        "HITL_KIND=schema_descriptions\n\n"
        "Respondé con **APPROVE** para aprobar, o pegá una versión corregida.\n\n"
        f"Borrador:\n{draft}"
    )
    state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
    return state


def schema_hitl_review(state: GraphState) -> GraphState:
    # Expect user message after the prompt.
    user = _last_user_text(state).strip()
    if user.upper() == "APPROVE":
        state["schema_hitl_pending"] = False
        state["schema_descriptions"] = state.get("schema_descriptions_draft", {})
        return state
    # If user provided edits, accept them as raw approved payload.
    if user:
        state["schema_hitl_pending"] = False
        state["schema_descriptions"] = {"raw_approved": user}
    return state


def schema_persist_descriptions(state: GraphState) -> GraphState:
    settings = get_settings()
    store = SchemaDescriptionsStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_descriptions.json")
    )
    store.save_approved(state.get("schema_descriptions", {}))
    state["messages"] = state.get("messages", []) + [
        AIMessage(content="Descripciones de schema guardadas (aprobadas).")
    ]
    return state


def query_load_context(state: GraphState) -> GraphState:
    settings = get_settings()
    prefs_store = PersistentStore(f"{settings.storage.data_dir}/user_preferences.json")
    state["user_preferences"] = prefs_store.load() or {}
    schema_store = SchemaDescriptionsStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_descriptions.json")
    )
    state["schema_descriptions"] = schema_store.load() or {}
    state.setdefault("short_term", {})
    return state


def query_planner(state: GraphState) -> GraphState:
    q = _last_user_text(state)
    state["query_plan"] = build_plan(q)
    return state


def query_sql_executor(state: GraphState) -> GraphState:
    agent = QueryAgent()
    q = _last_user_text(state)
    sql = agent.draft_sql(
        question=q,
        schema_descriptions=state.get("schema_descriptions", {}),
        schema_metadata=state.get("schema_metadata"),
        short_term=state.get("short_term", {}),
    )
    state["sql_draft"] = sql
    return state


def query_validator_node(state: GraphState) -> GraphState:
    sql = state.get("sql_draft", "")
    out = validate_sql_draft(sql)
    state["sql_validation"] = out.as_dict()
    state["query_hitl_pending"] = bool(out.needs_human_approval) or not bool(out.is_safe)
    if not out.is_safe:
        state["messages"] = state.get("messages", []) + [
            AIMessage(
                content="No puedo ejecutar ese SQL porque es inseguro. "
                f"Problemas: {out.issues}. "
                "Reformulá la pregunta o pedí un subconjunto con LIMIT."
            )
        ]
    return state


def query_hitl_review(state: GraphState) -> GraphState:
    # Only used when validator requests approval (e.g., missing LIMIT)
    sql = state.get("sql_draft", "")
    cid = new_checkpoint_id()
    msg = (
        "Antes de ejecutar, necesito aprobación humana (consulta riesgosa o muy amplia).\n\n"
        f"HITL_CHECKPOINT_ID={cid}\n"
        "HITL_KIND=sql_execution\n\n"
        "Respondé con **APPROVE** para ejecutar tal cual, o pegá un SQL corregido "
        "(solo SELECT).\n\n"
        f"SQL:\n{sql}"
    )
    state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
    # Wait for next user turn; keep pending.
    return state


def query_execute(state: GraphState) -> GraphState:
    # If user approved or provided edited SQL, use that. Otherwise use draft.
    user = _last_user_text(state).strip()
    sql = state.get("sql_draft", "")
    if user.upper() == "APPROVE":
        sql_to_run = sql
    elif user and "select" in user.lower():
        sql_to_run = user
    else:
        sql_to_run = sql
    state["sql_validated"] = sql_to_run
    try:
        state["query_result"] = sql_execute_readonly(sql=sql_to_run, timeout_ms=60_000)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 400:
            detail = _mcp_http_detail(e)
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
    res = state.get("query_result", {})
    if res.get("error"):
        return state
    sql = state.get("sql_validated", state.get("sql_draft", ""))
    content = (
        "SQL generado/ejecutado:\n"
        "```sql\n"
        f"{sql}\n"
        "```\n\n"
        f"Preview (hasta {len(res.get('rows', []) or [])} filas):\n"
        f"{res}\n\n"
        "Si querés, puedo refinar la consulta (filtros por fecha, top-N, etc.)."
    )
    state["messages"] = state.get("messages", []) + [AIMessage(content=content)]
    return state


def query_update_short_term_memory(state: GraphState) -> GraphState:
    st = state.get("short_term", {})
    st["last_sql_executed"] = state.get("sql_validated", state.get("sql_draft", ""))
    state["short_term"] = st
    return state


def build_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("router", router_node)

    # Schema flow
    g.add_node("schema_load", schema_load_existing_descriptions)
    g.add_node("schema_inspect", schema_inspect_metadata)
    g.add_node("schema_draft", schema_draft_descriptions)
    g.add_node("schema_hitl", schema_hitl_review)
    g.add_node("schema_persist", schema_persist_descriptions)

    # Query flow
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
        route_from_router,
        {"schema": "schema_load", "query": "query_load", "clarify": END},
    )

    # Schema chain
    g.add_edge("schema_load", "schema_inspect")
    g.add_edge("schema_inspect", "schema_draft")
    g.add_edge("schema_draft", "schema_hitl")
    g.add_conditional_edges(
        "schema_hitl",
        route_after_schema_hitl,
        {"persist": "schema_persist", "end": END},
    )
    g.add_edge("schema_persist", END)

    # Query chain
    g.add_edge("query_load", "query_plan")
    g.add_edge("query_plan", "query_sql")
    g.add_edge("query_sql", "query_validate")
    g.add_conditional_edges(
        "query_validate",
        route_after_query_validator,
        {"hitl": "query_hitl", "execute": "query_execute"},
    )
    # after hitl, execution happens on next turn; for simplicity in this MVP, we end after asking.
    g.add_edge("query_hitl", END)
    g.add_edge("query_execute", "query_explain")
    g.add_edge("query_explain", "query_mem")
    g.add_edge("query_mem", END)

    return g


_compiled = None


def get_compiled_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph().compile()
    return _compiled
