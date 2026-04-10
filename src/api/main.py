from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langserve import add_routes
from starlette.responses import StreamingResponse

from app_logging import configure_langsmith, configure_logging
from config.settings import get_settings
from contracts.openai_compat import (
    ChatCompletionsRequest,
    ChatCompletionsResponse,
    ChatCompletionsResponseChoice,
    ChatMessage,
)
from graph.workflow import get_compiled_graph

logger = logging.getLogger(__name__)

_STREAM_CHUNK_CHARS = 48
# Comentarios SSE mientras corre el grafo (evita timeouts de lectura en httpx/Open WebUI).
_STREAM_KEEPALIVE_SEC = 12.0


def _assistant_content_as_str(content: Any) -> str:
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


def _sse_chat_chunk(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: dict,
    finish_reason: str | None,
) -> bytes:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _run_graph_for_query(query: str) -> str:
    graph = get_compiled_graph()
    settings = get_settings()
    state = {
        "messages": [HumanMessage(content=query)],
        "session_id": "default",
    }
    out = graph.invoke(state, config={"recursion_limit": settings.graph.max_iterations})
    messages = out.get("messages", [])
    if not messages:
        return "No se generó respuesta."
    return _assistant_content_as_str(messages[-1].content)


async def _stream_chat_completion(*, query: str, model: str) -> StreamingResponse:
    completion_id = f"chatcmpl-{uuid.uuid4()}"
    created = int(time.time())

    async def event_gen():
        # Chunk inicial enseguida: evita que el cliente espere todo el grafo sin bytes (timeouts / chunked incompleto).
        yield _sse_chat_chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant", "content": ""},
            finish_reason=None,
        )
        task: asyncio.Task[str] = asyncio.create_task(
            asyncio.to_thread(_run_graph_for_query, query)
        )
        try:
            while True:
                done, _ = await asyncio.wait(
                    {task}, timeout=_STREAM_KEEPALIVE_SEC, return_when=asyncio.FIRST_COMPLETED
                )
                if task in done:
                    break
                yield b": keepalive\n\n"
            content = task.result()
        except Exception as e:
            logger.exception("stream_graph_failed")
            err = json.dumps(
                {"error": {"message": str(e), "type": "graph_error"}},
                ensure_ascii=False,
            )
            yield f"data: {err}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
            return

        for i in range(0, len(content), _STREAM_CHUNK_CHARS):
            piece = content[i : i + _STREAM_CHUNK_CHARS]
            yield _sse_chat_chunk(
                completion_id=completion_id,
                created=created,
                model=model,
                delta={"content": piece},
                finish_reason=None,
            )
        yield _sse_chat_chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={},
            finish_reason="stop",
        )
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def get_app() -> FastAPI:
    configure_logging()
    configure_langsmith()
    settings = get_settings()

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "healthy", "environment": settings.app.environment}

    @app.get("/v1/models")
    def list_models() -> dict:
        # Open WebUI: GET {OPENAI_API_BASE_URLS}/models — spec UI usa etiqueta tp-multiagentes.
        default_id = "tp-multiagentes"
        llm_id = (settings.llm.model or "").strip() or default_id
        ids: list[str] = []
        for mid in (default_id, llm_id):
            if mid and mid not in ids:
                ids.append(mid)
        now = int(time.time())
        return {
            "object": "list",
            "data": [
                {"id": mid, "object": "model", "created": now, "owned_by": "tp-multiagentes"}
                for mid in ids
            ],
        }

    runnable = get_compiled_graph()
    add_routes(app, runnable, path="/tp-agent")

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionsRequest):
        # Open WebUI suele mandar historial completo; el grafo usa el último mensaje user.
        last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)
        query = last_user.content if last_user else ""

        if req.stream:
            return await _stream_chat_completion(query=query, model=req.model)

        content = await asyncio.to_thread(_run_graph_for_query, query)
        return ChatCompletionsResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            created=int(time.time()),
            model=req.model,
            choices=[
                ChatCompletionsResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
        )

    return app
