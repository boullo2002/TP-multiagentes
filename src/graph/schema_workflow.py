from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from agents.schema_agent import SchemaAgent
from config.settings import get_settings
from graph.checkpoints import new_checkpoint_id
from graph.edges import is_approve_reply
from graph.state import GraphState
from memory.persistent_store import PersistentStore
from memory.schema_context_store import SchemaContextStore
from memory.user_preferences import normalize_user_preferences
from tools.mcp_client import MCPClientError
from tools.mcp_schema_tool import schema_inspect

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
    t.setdefault("llm_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    return t


def _record_node_latency(state: GraphState, node: str, started_at: float) -> None:
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    _traj(state)["node_latency_ms"][node] = elapsed_ms


def _add_event(state: GraphState, event: str, **extra: object) -> None:
    _traj(state)["events"].append({"event": event, **extra})


def _normalize_semantic_descriptions(payload: dict[str, Any]) -> dict[str, Any]:
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return {"tables": []}
    out: list[dict[str, Any]] = []
    for t in tables:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        cols_out: list[dict[str, str]] = []
        for c in t.get("columns") or []:
            if not isinstance(c, dict):
                continue
            c_name = str(c.get("name") or "").strip()
            if not c_name:
                continue
            cols_out.append(
                {"name": c_name, "description": str(c.get("description") or "").strip()}
            )
        out.append(
            {
                "name": name,
                "description": str(t.get("description") or "").strip(),
                "columns": cols_out,
            }
        )
    return {"tables": out}


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


def _mcp_client_detail(e: MCPClientError) -> str:
    d = e.detail
    if isinstance(d, dict):
        inner = d.get("detail", d)
        if isinstance(inner, dict):
            return str(inner.get("message", inner))[:2000]
        return str(inner)[:2000]
    return str(e)[:2000]


def _hydrate_schema_state(state: GraphState) -> None:
    settings = get_settings()
    prefs_store = PersistentStore(f"{settings.storage.data_dir}/user_preferences.json")
    state["user_preferences"] = normalize_user_preferences(prefs_store.load() or {})
    ctx_store = SchemaContextStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_context.json")
    )
    state["schema_context"] = ctx_store.load() or {}


def schema_router(state: GraphState) -> GraphState:
    _log_node("schema_router")
    msgs = state.get("messages", [])
    user_raw = _last_user_text(state).strip()
    prior_ai = _prior_assistant(msgs)

    if prior_ai and prior_ai.content and user_raw:
        c = prior_ai.content if isinstance(prior_ai.content, str) else str(prior_ai.content)
        if "HITL_KIND=schema_context" in c:
            state["mode"] = "schema_hitl_resume"
            return state

    state["mode"] = "schema"
    return state


def schema_load(state: GraphState) -> GraphState:
    _log_node("schema_load")
    _hydrate_schema_state(state)
    return state


def schema_inspect_metadata(state: GraphState) -> GraphState:
    _log_node("schema_inspect")
    try:
        state["schema_metadata"] = schema_inspect(schema=None, include_views=False)
    except MCPClientError as e:
        detail = _mcp_client_detail(e)
        state["schema_metadata"] = {}
        state["messages"] = state.get("messages", []) + [
            AIMessage(
                content=(
                    "No se pudo obtener el metadata del schema desde el servicio MCP. "
                    f"Detalle: {detail}"
                )
            )
        ]
    return state


def schema_draft_context(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("schema_draft_context")
    try:
        ctx = state.get("schema_context") or {}
        existing_md = ""
        answers: dict[str, Any] = {}
        if isinstance(ctx, dict):
            existing_md = str(ctx.get("context_markdown") or "")
            a = ctx.get("answers")
            if isinstance(a, dict):
                answers = a

        agent = SchemaAgent()
        draft_res = agent.draft_bundle(
            state.get("schema_metadata", {}),
            existing_context_markdown=existing_md,
            existing_semantic_descriptions=ctx.get("semantic_descriptions", {}),
            human_answers=answers,
            user_preferences=state.get("user_preferences", {}),
        )
        draft = draft_res.payload
        state["semantic_descriptions_draft"] = _normalize_semantic_descriptions(
            draft.get("semantic_descriptions", {})
        )
        usage = _traj(state)["llm_usage"]
        for k, v in draft_res.usage.items():
            usage[k] = int(usage.get(k, 0)) + int(v)

        state["schema_context_draft"] = draft
        questions = draft.get("questions") if isinstance(draft, dict) else None
        needs = bool(questions) and isinstance(questions, list) and len(questions) > 0
        state["schema_hitl_pending"] = needs

        if needs:
            cid = new_checkpoint_id()
            body = json.dumps(draft, ensure_ascii=False)
            msg = (
                "Necesito ayuda humana para resolver ambigüedades del schema antes de "
                "guardar el contexto.\n\n"
                f"HITL_CHECKPOINT_ID={cid}\n"
                "HITL_KIND=schema_context\n\n"
                "Respondé con **APPROVE** si el borrador ya está bien, "
                "o pegá un JSON con respuestas.\n"
                "Ejemplo:\n"
                '{"answers": {"q1": "Año de lanzamiento"}}\n\n'
                f"Borrador (JSON):\n{body}\n"
            )
            state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
            _add_event(state, "schema_hitl_requested")
            return state

        # Si no hay preguntas, persistimos directo.
        state["schema_hitl_pending"] = False
        return state
    finally:
        _record_node_latency(state, "schema_draft_context", started)


def schema_hitl_resume_loader(state: GraphState) -> GraphState:
    _log_node("schema_hitl_resume_loader")
    _hydrate_schema_state(state)
    user = _last_user_text(state).strip()
    if is_approve_reply(user):
        state["schema_hitl_pending"] = False
        return state
    # intentamos parsear JSON de respuestas
    try:
        blob = re.sub(r"```json\s*|\s*```", "", user, flags=re.I).strip()
        parsed = json.loads(blob)
        if isinstance(parsed, dict) and isinstance(parsed.get("answers"), dict):
            state["schema_context_answers"] = parsed["answers"]
    except Exception:
        state["schema_context_answers"] = {"raw": user}
    state["schema_hitl_pending"] = False
    return state


def schema_redraft_with_answers(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("schema_redraft_with_answers")
    try:
        ctx = state.get("schema_context") or {}
        existing_md = ""
        if isinstance(ctx, dict):
            existing_md = str(ctx.get("context_markdown") or "")
        answers = state.get("schema_context_answers") or {}

        agent = SchemaAgent()
        draft_res = agent.draft_bundle(
            state.get("schema_metadata", {}),
            existing_context_markdown=existing_md,
            existing_semantic_descriptions=ctx.get("semantic_descriptions", {}),
            human_answers=answers if isinstance(answers, dict) else {"raw": str(answers)},
            user_preferences=state.get("user_preferences", {}),
        )
        draft = draft_res.payload
        state["semantic_descriptions_draft"] = _normalize_semantic_descriptions(
            draft.get("semantic_descriptions", {})
        )
        usage = _traj(state)["llm_usage"]
        for k, v in draft_res.usage.items():
            usage[k] = int(usage.get(k, 0)) + int(v)

        state["schema_context_draft"] = draft
        questions = draft.get("questions") if isinstance(draft, dict) else None
        needs = bool(questions) and isinstance(questions, list) and len(questions) > 0
        state["schema_hitl_pending"] = needs
        if needs:
            # volvemos a pedir HITL
            cid = new_checkpoint_id()
            body = json.dumps(draft, ensure_ascii=False)
            msg = (
                "Todavía quedan ambigüedades. Necesito otra respuesta humana.\n\n"
                f"HITL_CHECKPOINT_ID={cid}\n"
                "HITL_KIND=schema_context\n\n"
                "Pegá un JSON con `answers`.\n\n"
                f"Borrador (JSON):\n{body}\n"
            )
            state["messages"] = state.get("messages", []) + [AIMessage(content=msg)]
            _add_event(state, "schema_hitl_requested")
        return state
    finally:
        _record_node_latency(state, "schema_redraft_with_answers", started)


def schema_persist_context(state: GraphState) -> GraphState:
    started = time.perf_counter()
    _log_node("schema_persist_context")
    try:
        settings = get_settings()
        store = SchemaContextStore(
            PersistentStore(f"{settings.storage.data_dir}/schema_context.json")
        )

        draft = state.get("schema_context_draft") or {}
        if not isinstance(draft, dict):
            draft = {"context_markdown": str(draft)}
        ctx_md = str(draft.get("context_markdown") or "")
        schema_hash = draft.get("schema_hash")
        questions = draft.get("questions") if isinstance(draft.get("questions"), list) else []
        answers = state.get("schema_context_answers") or {}
        sem_desc = state.get("semantic_descriptions_draft")

        store.save(
            context_markdown=ctx_md,
            schema_hash=str(schema_hash) if schema_hash is not None else None,
            semantic_descriptions=sem_desc if isinstance(sem_desc, dict) else {"tables": []},
            questions=questions,
            answers=answers if isinstance(answers, dict) else {"raw": str(answers)},
        )
        state["messages"] = state.get("messages", []) + [
            AIMessage(content="Contexto de schema guardado (aprobado).")
        ]
        _add_event(state, "schema_context_persisted")
        logger.info("trajectory_metrics=%s", _traj(state))
        return state
    finally:
        _record_node_latency(state, "schema_persist_context", started)


def build_schema_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("router", schema_router)
    g.add_node("schema_load", schema_load)
    g.add_node("schema_inspect_initial", schema_inspect_metadata)
    g.add_node("schema_inspect_resume", schema_inspect_metadata)
    g.add_node("schema_draft", schema_draft_context)
    g.add_node("schema_hitl_resume_loader", schema_hitl_resume_loader)
    g.add_node("schema_redraft", schema_redraft_with_answers)
    g.add_node("schema_persist", schema_persist_context)

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        lambda s: "hitl_resume" if s.get("mode") == "schema_hitl_resume" else "schema",
        {"hitl_resume": "schema_hitl_resume_loader", "schema": "schema_load"},
    )

    g.add_edge("schema_load", "schema_inspect_initial")
    g.add_edge("schema_inspect_initial", "schema_draft")

    # Si draft pidió HITL, terminamos con el mensaje. Si no, persistimos.
    g.add_conditional_edges(
        "schema_draft",
        lambda s: "hitl" if s.get("schema_hitl_pending") else "persist",
        {"hitl": END, "persist": "schema_persist"},
    )

    # Resume → re-draft → si todavía hay preguntas termina, si no persist.
    g.add_edge("schema_hitl_resume_loader", "schema_inspect_resume")
    g.add_edge("schema_inspect_resume", "schema_redraft")
    g.add_conditional_edges(
        "schema_redraft",
        lambda s: "hitl" if s.get("schema_hitl_pending") else "persist",
        {"hitl": END, "persist": "schema_persist"},
    )

    g.add_edge("schema_persist", END)
    return g


_compiled = None


def get_compiled_schema_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_schema_graph().compile(name="schema_context_hitl")
    return _compiled
