from __future__ import annotations

from graph.run_config import build_query_graph_invoke_config, sanitize_trace_preview


def test_sanitize_trace_preview() -> None:
    assert sanitize_trace_preview("  hola\nmundo  ") == "hola mundo"
    long = "x" * 100
    out = sanitize_trace_preview(long, max_len=10)
    assert len(out) == 10
    assert out.endswith("…")


def test_build_query_graph_invoke_config_shape() -> None:
    cfg = build_query_graph_invoke_config(
        user_question_preview="cuántos clientes",
        message_count=3,
        session_id="default",
        recursion_limit=80,
        environment="test",
        llm_model="gpt-4",
    )
    assert cfg["recursion_limit"] == 80
    assert cfg["run_name"].startswith("NLQ ·")
    assert "clientes" in cfg["run_name"]
    assert "workflow:nlq_query" in cfg["tags"]
    assert cfg["metadata"]["session_id"] == "default"
    assert cfg["metadata"]["message_count"] == 3
    assert cfg["metadata"]["user_preview"] == "cuántos clientes"
    assert cfg["metadata"]["llm_model"] == "gpt-4"
    tid = cfg["configurable"]["thread_id"]
    assert tid.startswith("http-")
    assert tid == cfg["metadata"]["trace_thread_id"]
