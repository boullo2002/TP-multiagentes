from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from starlette.responses import StreamingResponse

import api.openai_graph as openai_graph
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
_STREAM_KEEPALIVE_SEC = 12.0

_MCP_UNAVAILABLE_MSG = (
    "No se pudo conectar al servicio de datos (MCP). "
    "Verificá que el contenedor `mcp` esté en línea y que `MCP_SERVER_URL` sea correcto."
)


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


async def _stream_chat_completion(*, req: ChatCompletionsRequest) -> StreamingResponse:
    completion_id = f"chatcmpl-{uuid.uuid4()}"
    created = int(time.time())
    model = req.model

    async def event_gen():
        yield _sse_chat_chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant", "content": ""},
            finish_reason=None,
        )
        task: asyncio.Task[str] = asyncio.create_task(
            asyncio.to_thread(openai_graph.invoke_graph_for_chat_request, req.messages)
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
            if openai_graph.is_mcp_unavailable(e):
                err_text = _MCP_UNAVAILABLE_MSG
                yield _sse_chat_chunk(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    delta={"content": err_text},
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
                return
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
        if req.stream:
            return await _stream_chat_completion(req=req)

        try:
            content = await asyncio.to_thread(openai_graph.invoke_graph_for_chat_request, req.messages)
        except Exception as e:
            if openai_graph.is_mcp_unavailable(e):
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "mcp_unavailable",
                        "message": _MCP_UNAVAILABLE_MSG,
                    },
                ) from e
            raise

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
