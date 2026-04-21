from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import SystemMessage
from langsmith import traceable

from agents.prompts import SCHEMA_AGENT_SYSTEM_PROMPT
from llm.client import LLMClient
from memory.user_preferences import prefs_for_prompts


@dataclass(frozen=True)
class SchemaDraftResult:
    payload: dict[str, Any]
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
    """Agente 1/2: analiza schema y produce contexto persistente (spec-agents.md §2)."""

    def __init__(self) -> None:
        self._llm = LLMClient().get()

    @traceable(
        name="schema_agent_draft_descriptions",
        run_type="chain",
        tags=["workflow:schema", "agent:schema", "stage:descriptions"],
    )
    def draft_descriptions(
        self,
        schema_metadata: dict[str, Any],
        *,
        existing_descriptions: dict[str, Any] | None = None,
        user_preferences: dict[str, Any] | None = None,
    ) -> SchemaDraftResult:
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
        usage = _extract_usage(msg)
        parsed = _extract_json_object(raw)
        if parsed is not None:
            return SchemaDraftResult(payload=parsed, usage=usage)
        return SchemaDraftResult(payload={"raw": raw}, usage=usage)

    @traceable(
        name="schema_agent_draft_bundle",
        run_type="chain",
        tags=["workflow:schema", "agent:schema", "stage:bundle"],
    )
    def draft_bundle(
        self,
        schema_metadata: dict[str, Any],
        *,
        existing_context_markdown: str = "",
        existing_semantic_descriptions: dict[str, Any] | None = None,
        human_answers: dict[str, Any] | None = None,
        user_preferences: dict[str, Any] | None = None,
    ) -> SchemaDraftResult:
        """
        Devuelve JSON con:
        - context_markdown: str (resumen listo para que el Query Agent consuma)
        - semantic_descriptions: {"tables":[...]} con descripciones por tabla/columna
        - questions: list (si hay ambigüedades)
        - schema_hash: str | null (opcional)
        """
        prefs = user_preferences or {}
        p = prefs_for_prompts(prefs)
        lang = p["language"]
        answers = human_answers or {}
        sem = existing_semantic_descriptions or {}
        prompt = (
            f"Preferencias: idioma_salida={lang}.\n\n"
            "Tu objetivo es producir un CONTEXTO para que otro agente (Query Agent) "
            "pueda responder preguntas en lenguaje natural con SQL correcto.\n\n"
            "Reglas:\n"
            "- No inventes nada fuera del metadata.\n"
            "- Si hay nombres ambiguos (p. ej. columna `year`), generá preguntas concretas.\n"
            "- El contexto debe ser breve, orientado a joins típicos y campos clave.\n\n"
            "Contexto previo (si existe, actualizalo sin perder info válida):\n"
            f"{existing_context_markdown[:8000]}\n\n"
            "Respuestas humanas previas (si existen):\n"
            f"{json.dumps(answers, ensure_ascii=False)[:4000]}\n\n"
            "Descripciones semánticas previas (si existen, refiná sin perder info válida):\n"
            f"{json.dumps(sem, ensure_ascii=False)[:8000]}\n\n"
            "Metadata del schema (fuente de verdad):\n"
            f"{json.dumps(schema_metadata, ensure_ascii=False)[:14000]}\n\n"
            "Devolvé SOLO un JSON con esta forma aproximada:\n"
            '{ "context_markdown": "...", "semantic_descriptions": {"tables":[{"name":"...",'
            '"description":"...","columns":[{"name":"...","description":"..."}]}]},'
            ' "questions": [ {"id":"q1","question":"..."} ],'
            ' "schema_hash": "..." }\n'
            "Si no hay ambigüedades, `questions` debe ser []. Sin markdown."
        )
        msg = self._llm.invoke(
            [SystemMessage(content=SCHEMA_AGENT_SYSTEM_PROMPT), ("user", prompt)]
        )
        raw = msg.content if isinstance(msg.content, str) else str(msg.content)
        usage = _extract_usage(msg)
        parsed = _extract_json_object(raw)
        if parsed is not None:
            return SchemaDraftResult(payload=parsed, usage=usage)
        return SchemaDraftResult(
            payload={
                "raw": raw,
                "questions": [{"id": "parse_error", "question": "No pude parsear JSON."}],
                "semantic_descriptions": {"tables": []},
            },
            usage=usage,
        )

    # Backward-compatible alias
    def draft_context(
        self,
        schema_metadata: dict[str, Any],
        *,
        existing_context_markdown: str = "",
        human_answers: dict[str, Any] | None = None,
        user_preferences: dict[str, Any] | None = None,
    ) -> SchemaDraftResult:
        return self.draft_bundle(
            schema_metadata,
            existing_context_markdown=existing_context_markdown,
            existing_semantic_descriptions=None,
            human_answers=human_answers,
            user_preferences=user_preferences,
        )
