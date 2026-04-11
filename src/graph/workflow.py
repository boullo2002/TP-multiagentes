from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict

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


def _log_node(name: str) -> None:
    logger.info("graph_node=%s", name)


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
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""


def _prior_assistant(msgs: list) -> AIMessage | None:
    if len(msgs) < 2:
        return None
    for m in reversed(msgs[:-1]):
        if isinstance(m, AIMessage):
            return m
    return None


def _hitl_kind_from_assistant(ai: AIMessage | None) -> str | None:
    if not ai or not ai.content:
        return None
    c = ai.content if isinstance(ai.content, str) else str(ai.content)
    if "HITL_KIND=schema_descriptions" in c:
        return "schema_descriptions"
    if "HITL_KIND=sql_execution" in c:
        return "sql_execution"
    return None


def _extract_sql_block(content: str) -> str:
    marker = "SQL:\n"
    if marker not in content:
        return ""
    rest = content.split(marker, 1)[1].strip()
    block = rest.split("\n\n")[0] if rest else ""
    return block.strip()


def _looks_ambiguous(text: str) -> bool:
    t = text.lower().strip()
    if len(t) < 2:
        return True
    if t in ("approve", "aprobá", "aprobe", "ok", "sí", "si", "no"):
        return False
    if len(t) > 120:
        return False
    if any(
        k in t
        for k in [
            "schema",
            "tabla",
            "tablas",
            "columna",
            "columnas",
            "relación",
            "relaciones",
            "document",
            "select",
            "cuánt",
            "cuando",
            "lista",
            "mostrá",
            "mostrar",
            "describ",
            "dvd",
            "película",
            "alquiler",
            "cliente",
        ]
    ):
        return False
    if "?" in t:
        return False
    return len(t.split()) <= 4


def _hydrate_query_preferences(state: GraphState) -> None:
    settings = get_settings()
    prefs_store = PersistentStore(f"{settings.storage.data_dir}/user_preferences.json")
    state["user_preferences"] = prefs_store.load() or {}
    schema_store = SchemaDescriptionsStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_descriptions.json")
    )
    state["schema_descriptions"] = schema_store.load() or {}
    state.setdefault("short_term", {})


def router_node(state: GraphState) -> GraphState:
    _log_node("router")
    msgs = state.get("messages", [])
    user_raw = _last_user_text(state)
    text = user_raw.lower().strip()
    prior_ai = _prior_assistant(msgs)
    kind = _hitl_kind_from_assistant(prior_ai)

    if kind == "sql_execution" and user_raw.strip():
        state["mode"] = "query_hitl_resume"
        return state

    if kind == "schema_descriptions" and user_raw.strip():
        state["mode"] = "schema_hitl_resume"
        return state

    if _looks_ambiguous(text):
        state["mode"] = "clarify"
        return state

    if any(
        k in text
        for k in [
            "schema",
            "tablas",
            "columnas",
            "relaciones",
            "document",
            "documentá",
            "describí",
            "describe",
            "ddl",
        ]
    ):
        state["mode"] = "schema"
    else:
        state["mode"] = "query"
    return state


def clarify_node(state: GraphState) -> GraphState:
    _log_node("clarify")
    state["messages"] = state.get("messages", []) + [
        AIMessage(
            content=(
                "No estoy seguro de qué querés hacer. ¿Podés aclarar? "
                "Por ejemplo: una **pregunta sobre los datos** (ventas, películas, clientes) "
                "o **documentación del schema** (tablas, columnas, relaciones)."
            )
        )
    ]
    return state


def schema_hitl_resume_loader(state: GraphState) -> GraphState:
    _log_node("schema_hitl_resume_loader")
    msgs = state.get("messages", [])
    prior = _prior_assistant(msgs)
    draft: dict = {}
    if prior and prior.content:
        c = prior.content if isinstance(prior.content, str) else str(prior.content)
        marker = "Borrador (JSON):\n"
        if marker in c:
            blob = c.split(marker, 1)[1].strip()
            try:
                draft = json.loads(blob)
            except json.JSONDecodeError:
                draft = {"raw": blob}
    state["schema_descriptions_draft"] = draft
    state["schema_hitl_pending"] = True
    return state


def query_hitl_resume_loader(state: GraphState) -> GraphState:
    _log_node("query_hitl_resume_loader")
    _hydrate_query_preferences(state)
    msgs = state.get("messages", [])
    prior = _prior_assistant(msgs)
    sql = ""
    if prior and prior.content:
        c = prior.content if isinstance(prior.content, str) else str(prior.content)
        sql = _extract_sql_block(c)
    user = _last_user_text(state).strip()
    if user.upper() != "APPROVE" and "select" in user.lower():
        sql = re.sub(r"```sql\s*|\s*```", "", user, flags=re.I).strip()
    state["sql_draft"] = sql
    state["query_hitl_pending"] = False
    return state


def schema_load_existing_descriptions(state: GraphState) -> GraphState:
    _log_node("schema_load_existing_descriptions")
    settings = get_settings()
    store = SchemaDescriptionsStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_descriptions.json")
    )
    state["schema_descriptions"] = store.load() or {}
    return state


def schema_inspect_metadata(state: GraphState) -> GraphState:
    _log_node("schema_inspect_metadata")
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
    _log_node("schema_draft_descriptions")
    agent = SchemaAgent()
    draft = agent.draft_descriptions(state.get("schema_metadata", {}))
    state["schema_descriptions_draft"] = draft
    state["schema_hitl_pending"] = True
    cid = new_checkpoint_id()
    body = json.dumps(draft, ensure_ascii=False)
    msg = (
        "Necesito aprobación humana para guardar descripciones de schema.\n\n"
        f"HITL_CHECKPOINT_ID={cid}\n"
        "HITL_KIND=schema_descriptions\n\n"
        "Respondé con **APPROVE** para aprobar, o pegá una versión corregida.\n\n"
        f"Borrador (JSON):\n{body}\n"
    )
    state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
    return state


def schema_hitl_review(state: GraphState) -> GraphState:
    _log_node("schema_hitl_review")
    user = _last_user_text(state).strip()
    if user.upper() == "APPROVE":
        state["schema_hitl_pending"] = False
        state["schema_descriptions"] = state.get("schema_descriptions_draft", {})
        return state
    if user:
        state["schema_hitl_pending"] = False
        state["schema_descriptions"] = {"raw_approved": user}
    return state


def schema_persist_descriptions(state: GraphState) -> GraphState:
    _log_node("schema_persist_descriptions")
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
    _log_node("query_load_context")
    _hydrate_query_preferences(state)
    if not state.get("schema_metadata"):
        try:
            state["schema_metadata"] = schema_inspect(schema=None, include_views=False)
        except Exception as e:
            logger.warning("query_load_context schema_inspect_optional failed: %s", e)
            state["schema_metadata"] = {}
    return state


def query_planner(state: GraphState) -> GraphState:
    _log_node("query_planner")
    q = _last_user_text(state)
    plan = build_plan(q)
    state["query_plan"] = asdict(plan)
    return state


def query_sql_executor(state: GraphState) -> GraphState:
    _log_node("query_sql_executor")
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
    _log_node("query_validator")
    sql = state.get("sql_draft", "")
    out = validate_sql_draft(sql)
    state["sql_validation"] = out.as_dict()
    state["query_hitl_pending"] = bool(out.needs_human_approval) or not bool(out.is_safe)
    state.pop("last_error", None)
    if not out.is_safe:
        state["last_error"] = "; ".join(out.issues) if out.issues else "validación_sql"
        state["messages"] = state.get("messages", []) + [
            AIMessage(
                content="No puedo ejecutar ese SQL porque es inseguro. "
                f"Problemas: {out.issues}. "
                "Reformulá la pregunta o pedí un subconjunto con LIMIT."
            )
        ]
    return state


def query_hitl_review(state: GraphState) -> GraphState:
    _log_node("query_hitl_review")
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
    return state


def query_execute(state: GraphState) -> GraphState:
    _log_node("query_execute")
    user = _last_user_text(state).strip()
    sql = state.get("sql_draft", "")
    if user.upper() == "APPROVE":
        sql_to_run = sql
    elif user and "select" in user.lower():
        sql_to_run = re.sub(r"```sql\s*|\s*```", "", user, flags=re.I).strip()
    else:
        sql_to_run = sql
    state["sql_validated"] = sql_to_run
    state.pop("last_error", None)
    try:
        state["query_result"] = sql_execute_readonly(sql=sql_to_run, timeout_ms=60_000)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 400:
            detail = _mcp_http_detail(e)
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
    _log_node("query_update_short_term_memory")
    st = state.get("short_term", {})
    st["last_sql_executed"] = state.get("sql_validated", state.get("sql_draft", ""))
    plan = state.get("query_plan", {})
    if isinstance(plan, dict):
        st["open_assumptions"] = plan.get("assumptions", [])
        st["planned_tables"] = plan.get("tables", [])
    state["short_term"] = st
    return state


def build_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("router", router_node)

    g.add_node("clarify", clarify_node)
    g.add_node("schema_hitl_resume_loader", schema_hitl_resume_loader)
    g.add_node("query_hitl_resume_loader", query_hitl_resume_loader)

    g.add_node("schema_load", schema_load_existing_descriptions)
    g.add_node("schema_inspect", schema_inspect_metadata)
    g.add_node("schema_draft", schema_draft_descriptions)
    g.add_node("schema_hitl", schema_hitl_review)
    g.add_node("schema_persist", schema_persist_descriptions)

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
        {
            "schema": "schema_load",
            "query": "query_load",
            "clarify": "clarify",
            "schema_hitl_resume": "schema_hitl_resume_loader",
            "query_hitl_resume": "query_hitl_resume_loader",
        },
    )

    g.add_edge("clarify", END)

    g.add_edge("schema_hitl_resume_loader", "schema_hitl")
    g.add_edge("query_hitl_resume_loader", "query_validate")

    g.add_edge("schema_load", "schema_inspect")
    g.add_edge("schema_inspect", "schema_draft")
    g.add_edge("schema_draft", "schema_hitl")
    g.add_conditional_edges(
        "schema_hitl",
        route_after_schema_hitl,
        {"persist": "schema_persist", "end": END},
    )
    g.add_edge("schema_persist", END)

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


def get_compiled_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph().compile()
    return _compiled
