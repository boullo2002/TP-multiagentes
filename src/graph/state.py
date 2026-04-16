from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


class GraphState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    mode: Literal[
        "query",
        "schema",
        "schema_hitl_resume",
    ]
    session_id: str
    user_preferences: dict[str, Any]

    schema_metadata: dict[str, Any]
    schema_context: dict[str, Any]
    schema_context_draft: dict[str, Any]
    schema_context_answers: dict[str, Any]
    schema_hitl_pending: bool

    query_plan: dict[str, Any] | str
    sql_draft: str
    sql_validated: str
    sql_validation: dict[str, Any]
    query_retry_count: int
    query_retry_pending: bool
    query_retry_issues: list[str]
    query_blocked: bool
    query_result: dict[str, Any]

    short_term: dict[str, Any]
    # str sin Optional: evita {"type":"null"} en JSON Schema del playground LangServe.
    last_error: str
