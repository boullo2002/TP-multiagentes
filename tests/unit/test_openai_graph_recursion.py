from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

import api.openai_graph as openai_graph
from contracts.openai_compat import ChatMessage


def test_invoke_graph_returns_spanish_on_recursion(monkeypatch) -> None:
    graph = MagicMock()
    graph.invoke.side_effect = GraphRecursionError("limit")

    monkeypatch.setattr(openai_graph, "get_compiled_graph", lambda: graph)

    out = openai_graph.invoke_graph_for_chat_request(
        [ChatMessage(role="user", content="hola")],
    )
    assert "límite" in out.lower() or "limite" in out.lower()
    assert "Recursion limit" not in out
    graph.invoke.assert_called_once()
