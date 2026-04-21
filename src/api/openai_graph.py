"""Invocación del grafo compilado (mismo runnable que LangServe) desde el adapter OpenAI."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError

from config.settings import get_settings
from contracts.openai_compat import ChatMessage
from graph.workflow import get_compiled_graph
from tools.mcp_client import MCPClientError

logger = logging.getLogger(__name__)


_FOLLOWUP_SUGGESTION_MARKERS = (
    "### task: suggest 3-5 relevant follow-up questions",
    "suggest 3-5 relevant follow-up questions or prompts",
)


def _is_followup_suggestion_task(messages: list[ChatMessage]) -> bool:
    if not messages:
        return False
    last_user = None
    for m in reversed(messages):
        if m.role == "user":
            last_user = m
            break
    if last_user is None:
        return False
    t = (last_user.content or "").strip().lower()
    return any(marker in t for marker in _FOLLOWUP_SUGGESTION_MARKERS)


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


_MSG_RECURSION = (
    "Se alcanzó el límite interno de pasos para esta consulta (suele pasar si hace falta "
    "mucha corrección automática del SQL). Probá con una pregunta más concreta, o "
    "reformulá en una sola idea (qué dato, de qué tabla o período)."
)
_MSG_GRAPH_GENERIC = (
    "Hubo un problema interno al procesar tu mensaje. Probá de nuevo en unos segundos "
    "o reformulá la pregunta."
)


def stream_fallback_assistant_text(exc: BaseException) -> str | None:
    """Texto amable para SSE si falló el grafo (no MCP). Evita payload JSON de error en la UI."""
    if is_mcp_unavailable(exc):
        return None
    if isinstance(exc, GraphRecursionError):
        return _MSG_RECURSION
    return _MSG_GRAPH_GENERIC


def invoke_graph_for_chat_request(messages: list[ChatMessage]) -> str:
    """Ejecuta el mismo compiled graph que expone LangServe en `/tp-agent/invoke`."""
    # Algunos frontends (ej. Open WebUI) disparan requests automáticos para
    # sugerencias de follow-up. No forman parte del flujo del agente NL→SQL,
    # así que los ignoramos para evitar ruido/costo en LangSmith.
    if _is_followup_suggestion_task(messages):
        logger.info("skip_followup_suggestion_task")
        return ""

    graph = get_compiled_graph()
    settings = get_settings()
    lc_messages = chat_messages_to_langchain(messages)
    if not lc_messages:
        lc_messages = [HumanMessage(content="")]
    state = {
        "messages": lc_messages,
        "session_id": "default",
    }
    limit = int(settings.graph_recursion_limit)
    try:
        out = graph.invoke(state, config={"recursion_limit": limit})
    except GraphRecursionError:
        logger.warning("graph_recursion_limit_exceeded limit=%s", limit)
        return _MSG_RECURSION
    except MCPClientError:
        raise
    except Exception:
        logger.exception("graph_invoke_failed")
        return _MSG_GRAPH_GENERIC
    msgs = out.get("messages", [])
    if not msgs:
        return "No se generó respuesta."
    return assistant_content_as_str(msgs[-1].content)
