from __future__ import annotations

import re

_UNSAFE = re.compile(
    r"\b(insert|update|delete|alter|drop|truncate|create|grant|revoke)\b", re.IGNORECASE
)


def _is_single_statement(sql: str) -> bool:
    stripped = sql.strip()
    if ";" not in stripped:
        return True
    return stripped.endswith(";") and stripped.count(";") == 1


def _is_readonly_select(sql: str) -> bool:
    s = sql.strip().lstrip("(").strip()
    return s[:6].lower() == "select" or s[:4].lower() == "with"


def enforce_readonly(sql: str) -> None:
    """Defensa en profundidad (spec-mcp §3.4); debe alinearse con src/tools/sql_safety."""
    if not sql.strip():
        raise ValueError("SQL vacío.")
    if _UNSAFE.search(sql):
        raise ValueError("SQL contiene keywords no permitidas (DDL/DML).")
    if not _is_single_statement(sql):
        raise ValueError("SQL contiene múltiples statements; no se permite.")
    if not _is_readonly_select(sql):
        raise ValueError("Solo se permite SQL de lectura (SELECT).")
