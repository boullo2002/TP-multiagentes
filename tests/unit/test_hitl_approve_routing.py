from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from graph.edges import is_approve_reply, route_after_query_hitl_resume


def test_is_approve_reply_variants() -> None:
    assert is_approve_reply("APPROVE") is True
    assert is_approve_reply("approve") is True
    assert is_approve_reply("**APPROVE**") is True
    assert is_approve_reply("no") is False


def test_route_after_hitl_resume_approve_goes_execute() -> None:
    state = {
        "messages": [
            HumanMessage(content="pregunta"),
            AIMessage(content="HITL_KIND=sql_execution\n\nSQL:\nSELECT 1"),
            HumanMessage(content="APPROVE"),
        ]
    }
    assert route_after_query_hitl_resume(state) == "execute"


def test_route_after_hitl_resume_custom_sql_goes_validate() -> None:
    state = {
        "messages": [
            HumanMessage(content="pregunta"),
            AIMessage(content="HITL_KIND=sql_execution\n\nSQL:\nSELECT 1"),
            HumanMessage(content="SELECT 2 FROM film LIMIT 1"),
        ]
    }
    assert route_after_query_hitl_resume(state) == "validate"
