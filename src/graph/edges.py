from __future__ import annotations

import re
from typing import Literal

from graph.state import GraphState

_APPROVE_LINE = re.compile(r"^\s*[*_`]*\s*approve\s*[*_`]*\s*$", re.IGNORECASE)


def is_approve_reply(text: str) -> bool:
    """True si el usuario aprueba HITL (APPROVE, **APPROVE**, etc.)."""
    if not text or not text.strip():
        return False
    return bool(_APPROVE_LINE.match(text.strip()))


def route_from_router(
    state: GraphState,
) -> Literal["schema", "query", "clarify", "schema_hitl_resume", "query_hitl_resume"]:
    return state.get("mode", "query")


def route_after_schema_hitl(state: GraphState) -> Literal["persist", "end"]:
    return "persist" if not state.get("schema_hitl_pending", False) else "end"


def route_after_query_validator(state: GraphState) -> Literal["hitl", "execute"]:
    return "hitl" if state.get("query_hitl_pending", False) else "execute"


def route_after_query_hitl_resume(state: GraphState) -> Literal["execute", "validate"]:
    """
    Tras reanudar desde HITL SQL: si el usuario escribió APPROVE, ejecutar tal cual
    (no revalidar: el validador volvería a pedir HITL p.ej. por information_schema).
    Si pegó otro SQL, pasar por validación.
    """
    from langchain_core.messages import HumanMessage

    user = ""
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            user = m.content if isinstance(m.content, str) else str(m.content)
            break
    if is_approve_reply(user):
        return "execute"
    return "validate"
