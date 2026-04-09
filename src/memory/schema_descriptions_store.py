from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from memory.persistent_store import PersistentStore


@dataclass(frozen=True)
class SchemaDescriptionsStore:
    store: PersistentStore

    def load(self) -> dict[str, Any]:
        return self.store.load()

    def save_approved(self, descriptions: dict[str, Any]) -> None:
        payload = {
            "version": int(descriptions.get("version", 1)),
            "approved_by_human": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "tables": descriptions.get("tables", descriptions),
        }
        self.store.save(payload)
