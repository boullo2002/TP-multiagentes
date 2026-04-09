from __future__ import annotations

import re
from dataclasses import dataclass

_UNSAFE = re.compile(
    r"\b(insert|update|delete|alter|drop|truncate|create|grant|revoke)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class SafetyResult:
    ok: bool
    reason: str | None = None
    needs_human_approval: bool = False


def is_single_statement(sql: str) -> bool:
    # Very simple guard: forbid ';' anywhere except trailing whitespace.
    stripped = sql.strip()
    if ";" not in stripped:
        return True
    return stripped.endswith(";") and stripped.count(";") == 1


def is_readonly_select(sql: str) -> bool:
    s = sql.strip().lstrip("(").strip()
    return s[:6].lower() == "select" or s[:4].lower() == "with"


def validate_sql(sql: str, *, strictness: str = "strict") -> SafetyResult:
    if not sql.strip():
        return SafetyResult(ok=False, reason="SQL vacío.")
    if _UNSAFE.search(sql):
        return SafetyResult(ok=False, reason="SQL contiene keywords no permitidas (DDL/DML).")
    if not is_single_statement(sql):
        return SafetyResult(ok=False, reason="SQL contiene múltiples statements; no se permite.")
    if not is_readonly_select(sql):
        return SafetyResult(ok=False, reason="Solo se permite SQL de lectura (SELECT).")

    # Soft policies: require LIMIT under strictness.
    if strictness == "strict" and re.search(r"\blimit\b", sql, re.IGNORECASE) is None:
        return SafetyResult(ok=True, needs_human_approval=True, reason="Falta LIMIT (modo strict).")
    return SafetyResult(ok=True)
