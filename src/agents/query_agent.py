from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import SystemMessage

from agents.prompts import QUERY_AGENT_SYSTEM_PROMPT
from config.settings import get_settings
from llm.client import LLMClient
from memory.user_preferences import effective_response_language, prefs_for_prompts


@dataclass(frozen=True)
class SQLDraftResult:
    sql: str
    usage: dict[str, int]


def _extract_usage(msg: Any) -> dict[str, int]:
    meta = getattr(msg, "response_metadata", None) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    if not isinstance(usage, dict):
        return {}
    out: dict[str, int] = {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = usage.get(k)
        if isinstance(v, int):
            out[k] = v
    return out


class QueryAgent:
    """Agente 2/2: NL → SQL (executor; el plan va en planner.py) — spec-agents.md §3."""

    def __init__(self) -> None:
        self._llm = LLMClient().get()
        self._settings = get_settings()

    def draft_sql(
        self,
        *,
        question: str,
        query_plan: dict[str, Any] | None,
        schema_context_markdown: str,
        schema_catalog: dict[str, Any] | None,
        semantic_schema_descriptions: dict[str, Any] | None,
        short_term: dict[str, Any],
        retry_feedback: str = "",
        user_preferences: dict[str, Any] | None = None,
    ) -> SQLDraftResult:
        p = prefs_for_prompts(user_preferences or {})
        default_limit = p["default_limit"]
        out_fmt = p["output_format"]
        lang = effective_response_language(user_preferences or {}, question)

        catalog = schema_catalog if schema_catalog is not None else {}
        semantic = semantic_schema_descriptions if semantic_schema_descriptions is not None else {}
        plan = query_plan if isinstance(query_plan, dict) else {}
        prompt = (
            f"Pregunta del usuario: {question}\n\n"
            f"Preferencias: idioma={lang}, formato_salida_ui={out_fmt}, "
            f"formato_fechas={p['date_format']}, default_limit_usuario={default_limit}\n\n"
            "Plan del planner (paso previo obligatorio; respetá tablas/supuestos/pasos):\n"
            f"{plan}\n\n"
            "Contexto de schema (aprobado por humano; fuente principal para entender "
            "joins/campos):\n"
            f"{schema_context_markdown}\n\n"
            f"Catálogo estructurado de schema (tablas/columnas/PK/FK): {catalog}\n\n"
            "Descripciones semánticas aprobadas (tabla/columna):\n"
            f"{semantic}\n\n"
            f"Memoria de corto plazo (última SQL, supuestos): {short_term}\n\n"
            f"Feedback de validación previa (si existe): {retry_feedback}\n\n"
            "Generá SQL PostgreSQL de solo lectura que responda la pregunta.\n"
            "Incluí LIMIT si aplica (modo strict del sistema) salvo que el usuario pida "
            "explícitamente sin límite y sea seguro.\n"
            "Devolvé solo el SQL en una sola sentencia, sin markdown."
        )
        msg = self._llm.invoke([SystemMessage(content=QUERY_AGENT_SYSTEM_PROMPT), ("user", prompt)])
        out = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
        usage = _extract_usage(msg)
        if out.upper().startswith("CLARIFY:"):
            return SQLDraftResult(sql=out, usage=usage)
        sql = re.sub(r"^```sql\s*|\s*```$", "", out, flags=re.IGNORECASE | re.MULTILINE).strip()
        return SQLDraftResult(sql=sql, usage=usage)
