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


def route_after_schema_hitl(state: GraphState) -> Literal["persist", "end"]:
    return "persist" if not state.get("schema_hitl_pending", False) else "end"


def route_after_query_validator(state: GraphState) -> Literal["end", "execute"]:
    return "end" if state.get("query_blocked", False) else "execute"
