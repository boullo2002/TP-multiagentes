from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

from graph.query_workflow import (
    get_compiled_query_graph,
    query_basic_intents,
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


def test_query_basic_intents_tables_from_metadata() -> None:
    state = {
        "messages": [HumanMessage(content="qué tablas hay?")],
        "schema_context": {"table_names": ["film", "rental"]},
    }
    out = query_basic_intents(state)
    assert out.get("query_blocked") is True
    assert "film" in str(out["messages"][-1].content)
    assert "rental" in str(out["messages"][-1].content)


def test_query_basic_intents_capabilities() -> None:
    state = {"messages": [HumanMessage(content="qué podés hacer?")]}
    out = query_basic_intents(state)
    assert out.get("query_blocked") is True
    assert "consultas en lenguaje natural" in str(out["messages"][-1].content).lower()


def test_query_basic_intents_capabilities_single_word() -> None:
    state = {"messages": [HumanMessage(content="  capacidades  ")]}
    out = query_basic_intents(state)
    assert out.get("query_blocked") is True
    assert "consultas en lenguaje natural" in str(out["messages"][-1].content).lower()


def test_query_basic_intents_social_goes_to_sql_flow() -> None:
    state = {"messages": [HumanMessage(content="hola")]}
    out = query_basic_intents(state)
    assert out.get("query_blocked") is not True


def test_query_validator_clarify_stops_without_retry() -> None:
    state = {
        "messages": [HumanMessage(content="capacidades")],
        "sql_draft": "CLARIFY: ¿A qué tipo de capacidades te referís?",
        "query_retry_count": 0,
    }
    out = query_validator_node(state)
    assert out.get("query_blocked") is True
    assert out.get("query_retry_pending") is False
    assert "aclaración" in str(out["messages"][-1].content).lower()
    assert "¿A qué tipo" in str(out["messages"][-1].content)


def test_query_validator_sets_retry_before_blocking(monkeypatch) -> None:
    from config.settings import get_settings

    monkeypatch.setenv("QUERY_SQL_RETRY_MAX", "2")
    get_settings.cache_clear()
    state = {
        "messages": [HumanMessage(content="consulta")],
        "sql_draft": "DROP TABLE film;",
        "query_retry_count": 0,
    }
    out = query_validator_node(state)
    assert out.get("query_retry_pending") is True
    assert out.get("query_blocked") is False
    assert out.get("query_retry_count") == 1


def test_query_validator_blocks_when_retries_exhausted(monkeypatch) -> None:
    import os

    from config.settings import get_settings

    monkeypatch.setenv("QUERY_SQL_RETRY_MAX", "1")
    get_settings.cache_clear()
    assert get_settings().query_sql_retry_max == int(os.environ["QUERY_SQL_RETRY_MAX"])
    state = {
        "messages": [HumanMessage(content="consulta")],
        "sql_draft": "DROP TABLE film;",
        "query_retry_count": 2,
    }
    out = query_validator_node(state)
    assert out.get("query_retry_pending") is False
    assert out.get("query_blocked") is True
    assert "varios intentos automáticos" in str(out["messages"][-1].content)
