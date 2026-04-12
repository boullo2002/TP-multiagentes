from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionStore:
    """Memoria por sesión (spec-memory §3.2): opcional, complementa `short_term` en el estado."""

    _sessions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, session_id: str) -> dict[str, Any]:
        return self._sessions.setdefault(session_id, {})

    def set(self, session_id: str, key: str, value: Any) -> None:
        self._sessions.setdefault(session_id, {})[key] = value


_store = SessionStore()


def get_session_store() -> SessionStore:
    return _store
