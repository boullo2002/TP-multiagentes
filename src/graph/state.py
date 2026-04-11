from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


class GraphState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    mode: Literal[
        "schema",
        "query",
        "clarify",
        "schema_hitl_resume",
        "query_hitl_resume",
    ]
    session_id: str
    user_preferences: dict[str, Any]

    schema_metadata: dict[str, Any]
    schema_descriptions: dict[str, Any]
    schema_descriptions_draft: dict[str, Any]
    schema_hitl_pending: bool

    query_plan: dict[str, Any] | str
    sql_draft: str
    sql_validated: str
    sql_validation: dict[str, Any]
    query_hitl_pending: bool
    query_result: dict[str, Any]

    short_term: dict[str, Any]
    # str sin Optional: evita {"type":"null"} en JSON Schema del playground LangServe.
    last_error: str
