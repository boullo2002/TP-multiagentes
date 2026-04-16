from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

from graph.query_workflow import (
    get_compiled_query_graph,
    query_load_context,
    query_sql_executor,
    query_validator_node,
    router_node,
)
from graph.schema_workflow import get_compiled_schema_graph


def test_graphs_compile() -> None:
    # Given / When
    gq = get_compiled_query_graph()
    gs = get_compiled_schema_graph()
    # Then
    assert gq.get_graph().nodes
    assert gs.get_graph().nodes


def test_query_router_defaults_to_query() -> None:
    state = {"messages": [HumanMessage(content="cuántos clientes hay en total")]}
    assert router_node(dict(state))["mode"] == "query"


def test_query_flow_sql_draft_then_validator(monkeypatch, tmp_data_dir) -> None:
    # Given: QueryAgent stub + metadata mínimo
    class _FakeQueryAgent:
        def draft_sql(self, **kwargs):
            return "SELECT film_id FROM film LIMIT 5"

    monkeypatch.setattr("graph.query_workflow.QueryAgent", _FakeQueryAgent)
    # y un schema_context persistido (requisito para el Query Agent)
    (tmp_data_dir / "schema_context.json").write_text(
        json.dumps({"context_markdown": "Tablas principales: film, rental.", "version": 1}),
        encoding="utf-8",
    )
    state = {
        "messages": [HumanMessage(content="listado de ids de película")],
        "session_id": "t-graph",
        "schema_metadata": {"tables": [{"name": "film"}]},
        "short_term": {},
    }
    # When: load_context → executor → validator
    state = query_load_context(state)
    state = query_sql_executor(state)
    assert state.get("sql_draft", "").startswith("SELECT")
    state = query_validator_node(state)
    # Then: validación presente antes de cualquier execute
    assert "sql_validation" in state
    v = state["sql_validation"]
    assert "is_safe" in v
