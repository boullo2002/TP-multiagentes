from __future__ import annotations

from langchain_openai import ChatOpenAI

from config.settings import get_settings


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._llm = ChatOpenAI(
            base_url=settings.llm.base_url or None,
            api_key=settings.llm.api_key or "dummy-key",
            model=settings.llm.model,
            temperature=0.0,
        )

    def get(self) -> ChatOpenAI:
        return self._llm
