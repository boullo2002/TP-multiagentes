from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage

from agents.prompts import SCHEMA_AGENT_SYSTEM_PROMPT
from llm.client import LLMClient


class SchemaAgent:
    def __init__(self) -> None:
        self._llm = LLMClient().get()

    def draft_descriptions(self, schema_metadata: dict[str, Any]) -> dict[str, Any]:
        # Minimal description drafting via LLM: give metadata and ask for concise descriptions.
        prompt = (
            "Generá descripciones en español para tablas y columnas.\n\n"
            "Metadata (JSON):\n"
            f"{schema_metadata}\n\n"
            "Devolvé un JSON con shape:\n"
            "{tables: {<table>: {description: str, columns: {<col>: str}}}}"
        )
        msg = self._llm.invoke(
            [SystemMessage(content=SCHEMA_AGENT_SYSTEM_PROMPT), ("user", prompt)]
        )
        # Keep as raw text if parse fails; workflow will present to HITL.
        return {"raw": msg.content}
