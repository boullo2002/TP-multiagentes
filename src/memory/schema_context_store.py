from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from memory.persistent_store import PersistentStore


@dataclass(frozen=True)
class SchemaContextStore:
    """Artifact persistente del Schema Agent para consumo del Query Agent."""

    store: PersistentStore

    def load(self) -> dict[str, Any]:
        raw = self.store.load()
        return raw if isinstance(raw, dict) else {}

    def save(
        self,
        *,
        context_markdown: str,
        schema_hash: str | None = None,
        table_names: list[str] | None = None,
        schema_catalog: dict[str, Any] | None = None,
        semantic_descriptions: dict[str, Any] | None = None,
        questions: list[dict[str, Any]] | None = None,
        answers: dict[str, Any] | None = None,
        version: int | None = None,
    ) -> None:
        prev = self.load()
        prev_ver = int(prev.get("version", 0) or 0)
        new_ver = int(version or (prev_ver + 1 if prev_ver else 1))
        payload: dict[str, Any] = {
            "version": new_ver,
            "generated_at": datetime.now(UTC).isoformat(),
            "schema_hash": schema_hash,
            "table_names": table_names or [],
            "schema_catalog": schema_catalog or {},
            "semantic_descriptions": semantic_descriptions or {"tables": []},
            "context_markdown": context_markdown,
            "questions": questions or [],
            "answers": answers or {},
            "approved_by_human": True,
        }
        self.store.save(payload)

