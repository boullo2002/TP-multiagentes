from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import SystemMessage

from agents.prompts import SCHEMA_AGENT_SYSTEM_PROMPT
from llm.client import LLMClient
from memory.user_preferences import prefs_for_prompts


def _extract_json_object(text: str) -> dict[str, Any] | None:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t).strip()
    try:
        val = json.loads(t)
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            try:
                val = json.loads(m.group(0))
                return val if isinstance(val, dict) else None
            except json.JSONDecodeError:
                return None
        return None


class SchemaAgent:
    """Agente 1/2: documentación de schema + borrador para HITL (spec-agents.md §2)."""

    def __init__(self) -> None:
        self._llm = LLMClient().get()

    def draft_descriptions(
        self,
        schema_metadata: dict[str, Any],
        *,
        existing_descriptions: dict[str, Any] | None = None,
        user_preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = existing_descriptions or {}
        if isinstance(existing, dict) and "tables" in existing:
            existing_for_prompt = existing
        else:
            existing_for_prompt = {"tables": existing} if existing else {}
        prefs = user_preferences or {}
        p = prefs_for_prompts(prefs)
        lang = p["language"]
        detail = prefs.get("detail_level", "normal")

        prompt = (
            f"Preferencias: idioma_salida={lang}, nivel_detalle={detail}.\n\n"
            "Descripciones ya aprobadas (refiná/extendé; el metadata manda sobre nombres/tipos):\n"
            f"{json.dumps(existing_for_prompt, ensure_ascii=False)[:8000]}\n\n"
            "Metadata del schema (fuente de verdad; no inventes fuera de esto):\n"
            f"{json.dumps(schema_metadata, ensure_ascii=False)[:14000]}\n\n"
            "Devolvé un único JSON con forma libre pero útil, por ejemplo:\n"
            '{"tables": [...], "relationships_summary": "..."} '
            'o {"needs_clarification": true, "reason": "..."}\n'
            "Sin markdown ni texto fuera del JSON."
        )
        msg = self._llm.invoke(
            [SystemMessage(content=SCHEMA_AGENT_SYSTEM_PROMPT), ("user", prompt)]
        )
        raw = msg.content if isinstance(msg.content, str) else str(msg.content)
        parsed = _extract_json_object(raw)
        if parsed is not None:
            return parsed
        return {"raw": raw}
