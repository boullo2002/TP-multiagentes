from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from memory.persistent_store import PersistentStore


@dataclass(frozen=True)
class SchemaDescriptionsStore:
    store: PersistentStore

    def load(self) -> dict[str, Any]:
        raw = self.store.load()
        if not raw or not isinstance(raw, dict):
            return {}
        if "tables" in raw:
            return raw
        inner = {
            k: v
            for k, v in raw.items()
            if k not in ("version", "generated_at", "approved_by_human")
        }
        return {
            "version": int(raw.get("version", 1)),
            "generated_at": raw.get("generated_at"),
            "approved_by_human": raw.get("approved_by_human", True),
            "tables": inner,
        }

    def save_approved(self, descriptions: dict[str, Any]) -> None:
        tables_payload = descriptions.get("tables")
        if tables_payload is None:
            tables_payload = {
                k: v
                for k, v in descriptions.items()
                if k
                not in (
                    "version",
                    "generated_at",
                    "approved_by_human",
                    "raw",
                    "needs_clarification",
                    "reason",
                )
            }
        prev = self.load()
        prev_ver = 0
        if isinstance(prev.get("version"), int):
            prev_ver = prev["version"]
        new_ver = int(descriptions.get("version", prev_ver + 1 if prev_ver else 1))

        payload: dict[str, Any] = {
            "version": new_ver,
            "approved_by_human": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "tables": tables_payload,
        }
        if rs := descriptions.get("relationships_summary"):
            payload["relationships_summary"] = rs
        self.store.save(payload)
