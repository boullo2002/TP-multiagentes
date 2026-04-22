"""Config de invocación del grafo para LangSmith (run_name, tags, metadata, thread_id)."""

from __future__ import annotations

import re
import uuid
from typing import Any


def sanitize_trace_preview(text: str, *, max_len: int = 72) -> str:
    """Texto corto y seguro para títulos de trace (sin saltos de línea ni control chars)."""
    s = (text or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[\x00-\x1f\x7f]", "", s)
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s or "(sin pregunta)"


def build_query_graph_invoke_config(
    *,
    user_question_preview: str,
    message_count: int,
    session_id: str,
    recursion_limit: int,
    environment: str,
    llm_model: str,
) -> dict[str, Any]:
    """
    Config para `graph.invoke(..., config=...)`.

    - `run_name`: identifica el run en la lista de LangSmith.
    - `configurable.thread_id`: un hilo por petición HTTP (evita mezclar runs en LangSmith).
    - `metadata`: filtros en LangSmith (`user_preview`, `env`, modelo).
    """
    preview = sanitize_trace_preview(user_question_preview)
    trace_thread = f"http-{uuid.uuid4().hex[:16]}"
    run_name = f"NLQ · {preview}"
    if len(run_name) > 120:
        run_name = run_name[:119] + "…"
    return {
        "recursion_limit": recursion_limit,
        "run_name": run_name,
        "tags": [
            "app:tp-multiagentes",
            "workflow:nlq_query",
            "entrypoint:openai_compat",
            f"env:{environment}",
        ],
        "metadata": {
            "graph": "query_nlq",
            "session_id": session_id,
            "trace_thread_id": trace_thread,
            "entrypoint": "v1/chat/completions",
            "message_count": message_count,
            "user_preview": preview,
            "llm_model": llm_model,
        },
        "configurable": {"thread_id": trace_thread},
    }
