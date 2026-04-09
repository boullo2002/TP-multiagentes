from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langserve import add_routes

from app_logging import configure_langsmith, configure_logging
from config.settings import get_settings
from contracts.openai_compat import (
    ChatCompletionsRequest,
    ChatCompletionsResponse,
    ChatCompletionsResponseChoice,
    ChatMessage,
)
from graph.workflow import get_compiled_graph


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
    return messages[-1].content


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

    runnable = get_compiled_graph()
    add_routes(app, runnable, path="/tp-agent")

    @app.post("/v1/chat/completions", response_model=ChatCompletionsResponse)
    def chat_completions(req: ChatCompletionsRequest) -> ChatCompletionsResponse:
        # For now, use last user message to drive the graph (OpenAIWeb likely sends full history).
        last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)
        query = last_user.content if last_user else ""
        content = _run_graph_for_query(query)
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
