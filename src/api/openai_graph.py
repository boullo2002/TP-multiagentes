"""Invocación del grafo compilado (mismo runnable que LangServe) desde el adapter OpenAI."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config.settings import get_settings
from contracts.openai_compat import ChatMessage
from graph.workflow import get_compiled_graph
from tools.mcp_client import MCPClientError

logger = logging.getLogger(__name__)


def assistant_content_as_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(str(block["text"]))
                elif "text" in block:
                    parts.append(str(block["text"]))
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def chat_messages_to_langchain(messages: list[ChatMessage]) -> list:
    """Convierte el cuerpo OpenAI al formato de mensajes LangChain del GraphState."""
    out: list = []
    for m in messages:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
        else:
            out.append(SystemMessage(content=m.content))
    return out


def is_mcp_unavailable(exc: BaseException) -> bool:
    """Errores de transporte hacia MCP → 503 en la API (spec §4.6)."""
    if isinstance(exc, MCPClientError):
        sc = exc.status_code
        return sc is None or sc >= 502
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ),
    ):
        return True
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, MCPClientError):
            sc = cur.status_code
            if sc is None or sc >= 502:
                return True
        if isinstance(
            cur,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def invoke_graph_for_chat_request(messages: list[ChatMessage]) -> str:
    """Ejecuta el mismo compiled graph que expone LangServe en `/tp-agent/invoke`."""
    graph = get_compiled_graph()
    settings = get_settings()
    lc_messages = chat_messages_to_langchain(messages)
    if not lc_messages:
        lc_messages = [HumanMessage(content="")]
    state = {
        "messages": lc_messages,
        "session_id": "default",
    }
    out = graph.invoke(state, config={"recursion_limit": settings.graph.max_iterations})
    msgs = out.get("messages", [])
    if not msgs:
        return "No se generó respuesta."
    return assistant_content_as_str(msgs[-1].content)
