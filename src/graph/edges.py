from __future__ import annotations

from typing import Literal

from graph.state import GraphState


def route_from_router(state: GraphState) -> Literal["schema", "query", "clarify"]:
    return state.get("mode", "query")


def route_after_schema_hitl(state: GraphState) -> Literal["persist", "end"]:
    return "persist" if not state.get("schema_hitl_pending", False) else "end"


def route_after_query_validator(state: GraphState) -> Literal["hitl", "execute"]:
    return "hitl" if state.get("query_hitl_pending", False) else "execute"
