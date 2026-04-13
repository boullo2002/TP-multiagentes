from __future__ import annotations

from langchain_core.messages import HumanMessage

from graph.workflow import (
    get_compiled_graph,
    query_sql_executor,
    query_validator_node,
    router_node,
    schema_draft_descriptions,
)


def test_graph_compiles() -> None:
    # Given / When
    g = get_compiled_graph()
    # Then
    assert g.get_graph().nodes


def test_router_schema_vs_query() -> None:
    # Given: mensajes representativos
    s_schema = {"messages": [HumanMessage(content="documentá las tablas del schema")]}
    s_query = {"messages": [HumanMessage(content="cuántos clientes hay en total")]}
    s_tables = {"messages": [HumanMessage(content="decime que tablas hay")]}
    # When / Then
    assert router_node(dict(s_schema))["mode"] == "schema"
    assert router_node(dict(s_query))["mode"] == "query"
    assert router_node(dict(s_tables))["mode"] == "query"


def test_schema_draft_sets_hitl_pending(monkeypatch) -> None:
    # Given: agente que no llama al LLM
    class _FakeSchemaAgent:
        def draft_descriptions(self, *a, **k):
            return {"tables": {"x": 1}}

    monkeypatch.setattr("graph.workflow.SchemaAgent", _FakeSchemaAgent)
    state = {
        "messages": [HumanMessage(content="hola")],
        "schema_metadata": {"tables": []},
        "schema_descriptions": {},
        "user_preferences": {},
    }
    # When
    out = schema_draft_descriptions(state)
    # Then
    assert out.get("schema_hitl_pending") is True
    assert "HITL_KIND=schema_descriptions" in (out["messages"][-1].content or "")


def test_query_flow_sql_draft_then_validator(monkeypatch, tmp_data_dir) -> None:
    # Given: QueryAgent stub + metadata mínimo
    class _FakeQueryAgent:
        def draft_sql(self, **kwargs):
            return "SELECT film_id FROM film LIMIT 5"

    monkeypatch.setattr("graph.workflow.QueryAgent", _FakeQueryAgent)
    state = {
        "messages": [HumanMessage(content="listado de ids de película")],
        "session_id": "t-graph",
        "schema_metadata": {"tables": [{"name": "film"}]},
        "schema_descriptions": {},
        "short_term": {},
    }
    # When: executor → validator
    state = query_sql_executor(state)
    assert state.get("sql_draft", "").startswith("SELECT")
    state = query_validator_node(state)
    # Then: validación presente antes de cualquier execute
    assert "sql_validation" in state
    v = state["sql_validation"]
    assert "is_safe" in v
