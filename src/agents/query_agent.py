from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import SystemMessage

from agents.prompts import QUERY_AGENT_SYSTEM_PROMPT
from config.settings import get_settings
from llm.client import LLMClient
from memory.user_preferences import prefs_for_prompts


class QueryAgent:
    """Agente 2/2: NL → SQL (executor; el plan va en planner.py) — spec-agents.md §3."""

    def __init__(self) -> None:
        self._llm = LLMClient().get()
        self._settings = get_settings()

    def draft_sql(
        self,
        *,
        question: str,
        schema_context_markdown: str,
        schema_metadata: dict[str, Any] | None,
        short_term: dict[str, Any],
        user_preferences: dict[str, Any] | None = None,
    ) -> str:
        p = prefs_for_prompts(user_preferences or {})
        default_limit = p["default_limit"]
        out_fmt = p["output_format"]
        lang = p["language"]

        meta = schema_metadata if schema_metadata is not None else {}
        prompt = (
            f"Pregunta del usuario: {question}\n\n"
            f"Preferencias: idioma={lang}, formato_salida_ui={out_fmt}, "
            f"formato_fechas={p['date_format']}, default_limit_usuario={default_limit}\n\n"
            "Contexto de schema (aprobado por humano; fuente principal para entender "
            "joins/campos):\n"
            f"{schema_context_markdown}\n\n"
            f"Metadata de tablas/columnas (referencia): {meta}\n\n"
            f"Memoria de corto plazo (última SQL, supuestos): {short_term}\n\n"
            "Generá SQL PostgreSQL de solo lectura que responda la pregunta.\n"
            "Incluí LIMIT si aplica (modo strict del sistema) salvo que el usuario pida "
            "explícitamente sin límite y sea seguro.\n"
            "Devolvé solo el SQL en una sola sentencia, sin markdown."
        )
        msg = self._llm.invoke([SystemMessage(content=QUERY_AGENT_SYSTEM_PROMPT), ("user", prompt)])
        out = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
        if out.upper().startswith("CLARIFY:"):
            return out
        return re.sub(r"^```sql\s*|\s*```$", "", out, flags=re.IGNORECASE | re.MULTILINE).strip()
