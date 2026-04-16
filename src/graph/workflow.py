"""Compat: el runnable principal ahora es el Query Agent."""

from __future__ import annotations

from graph.query_workflow import build_query_graph, get_compiled_query_graph


def get_compiled_graph():
    # Backwards compatible import path: `graph.workflow.get_compiled_graph()`
    return get_compiled_query_graph()


def build_graph():
    # Backwards compatible import path: `graph.workflow.build_graph()`
    return build_query_graph()
