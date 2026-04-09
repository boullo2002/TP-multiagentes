from __future__ import annotations

import re

_UNSAFE = re.compile(
    r"\b(insert|update|delete|alter|drop|truncate|create|grant|revoke)\b", re.IGNORECASE
)


def enforce_readonly(sql: str) -> None:
    if not sql.strip():
        raise ValueError("SQL vacío.")
    if _UNSAFE.search(sql):
        raise ValueError("SQL contiene keywords no permitidas (DDL/DML).")
    stripped = sql.strip()
    if ";" in stripped and not (stripped.endswith(";") and stripped.count(";") == 1):
        raise ValueError("SQL contiene múltiples statements; no se permite.")
    s = stripped.lstrip("(").strip().lower()
    if not (s.startswith("select") or s.startswith("with")):
        raise ValueError("Solo se permite SQL de lectura (SELECT).")
