from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage

from agents.prompts import QUERY_AGENT_SYSTEM_PROMPT
from config.settings import get_settings
from llm.client import LLMClient


class QueryAgent:
    def __init__(self) -> None:
        self._llm = LLMClient().get()
        self._settings = get_settings()

    def draft_sql(
        self,
        *,
        question: str,
        schema_descriptions: dict[str, Any],
        schema_metadata: dict[str, Any] | None,
        short_term: dict[str, Any],
    ) -> str:
        default_limit = self._settings.safety.default_limit
        prompt = (
            "Generá SQL (PostgreSQL) de SOLO LECTURA para responder.\n"
            f"Pregunta: {question}\n\n"
            f"Preferencias: default_limit={default_limit}\n\n"
            f"Schema descriptions (aprobadas o raw): {schema_descriptions}\n\n"
            f"Schema metadata: {schema_metadata}\n\n"
            f"Contexto corto plazo: {short_term}\n\n"
            "Reglas: solo SELECT. Incluí LIMIT si el usuario no pidió lo contrario.\n"
            "Devolvé SOLO el SQL (sin markdown)."
        )
        msg = self._llm.invoke([SystemMessage(content=QUERY_AGENT_SYSTEM_PROMPT), ("user", prompt)])
        return msg.content.strip()
