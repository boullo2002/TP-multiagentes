from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import add_messages


class GraphState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    mode: Literal["schema", "query", "clarify"]
    session_id: str
    user_preferences: dict[str, Any]

    schema_metadata: dict[str, Any]
    schema_descriptions: dict[str, Any]
    schema_descriptions_draft: dict[str, Any]
    schema_hitl_pending: bool

    query_plan: Any
    sql_draft: str
    sql_validated: str
    sql_validation: dict[str, Any]
    query_hitl_pending: bool
    query_result: dict[str, Any]

    short_term: dict[str, Any]
    last_error: str
