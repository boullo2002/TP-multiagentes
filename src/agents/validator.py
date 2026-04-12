from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from config.settings import get_settings
from memory.user_preferences import normalize_user_preferences
from tools.sql_safety import SafetyResult, validate_sql


@dataclass(frozen=True)
class ValidationOutput:
    is_safe: bool
    needs_human_approval: bool
    issues: list[str]
    suggested_sql: str | None

    def as_dict(self) -> dict:
        return asdict(self)


# Palabras que pueden aparecer tras JOIN y no son tablas.
_JOIN_NOISE = frozenset(
    {
        "lateral",
        "unnest",
        "inner",
        "left",
        "right",
        "full",
        "cross",
        "outer",
        "natural",
        "using",
        "on",
        "select",
    }
)


def _known_tables_from_metadata(schema_metadata: dict[str, Any] | None) -> set[str]:
    if not schema_metadata:
        return set()
    tables = schema_metadata.get("tables") or []
    return {str(t.get("name", "")).lower() for t in tables if t.get("name")}


def _extract_table_refs(sql: str) -> list[str]:
    """Referencias tipo schema.tabla o tabla tras FROM / JOIN (heurística)."""
    refs: list[str] = []
    for m in re.finditer(
        r"\b(?:FROM|JOIN)\s+(?:ONLY\s+)?(?!\()"
        r'(?:(?P<sch>[a-z_][a-z0-9_]*)\.)?(?P<tbl>"[^"]+"|[a-z_][a-z0-9_]*)',
        sql,
        re.I,
    ):
        raw = m.group("tbl") or ""
        name = raw.strip('"').strip()
        low = name.lower()
        if not name or low in _JOIN_NOISE:
            continue
        refs.append(name)
    return refs


def _schema_match_issues(sql: str, schema_metadata: dict[str, Any] | None) -> list[str]:
    known = _known_tables_from_metadata(schema_metadata)
    if not known:
        return []
    issues: list[str] = []
    for ref in _extract_table_refs(sql):
        if ref.lower() not in known:
            issues.append(f"Tabla no encontrada en el esquema conocido: {ref}")
    return issues


def _append_limit_clause(sql: str, limit: int) -> str:
    s = sql.strip().rstrip(";")
    if re.search(r"\blimit\b", s, re.I):
        return sql.strip()
    return f"{s} LIMIT {limit}"


def validate_sql_draft(
    sql: str,
    *,
    schema_metadata: dict[str, Any] | None = None,
    user_preferences: dict[str, Any] | None = None,
) -> ValidationOutput:
    settings = get_settings()
    prefs = normalize_user_preferences(user_preferences or {})
    strictness = str(prefs.get("sql_safety_strictness") or settings.safety.sql_safety_strictness)
    if strictness not in ("strict", "balanced"):
        strictness = settings.safety.sql_safety_strictness
    default_limit = int(prefs.get("default_limit", settings.safety.default_limit))

    res: SafetyResult = validate_sql(sql, strictness=strictness)
    issues: list[str] = []
    suggested_sql: str | None = None

    if not res.ok:
        issues.append(res.reason or "SQL inválido.")
    if res.needs_human_approval:
        issues.append(res.reason or "Requiere aprobación humana.")

    schema_issues = _schema_match_issues(sql, schema_metadata)
    issues.extend(schema_issues)

    needs_hitl = bool(res.needs_human_approval) or bool(schema_issues)
    if not res.ok:
        needs_hitl = True

    # Auto-fix opcional: añadir LIMIT cuando falta (modo strict) pero el SQL es válido.
    if res.ok and res.needs_human_approval and strictness == "strict":
        if re.search(r"\blimit\b", sql, re.I) is None:
            suggested_sql = _append_limit_clause(sql, default_limit)

    is_safe = res.ok and not schema_issues

    return ValidationOutput(
        is_safe=is_safe,
        needs_human_approval=needs_hitl,
        issues=issues,
        suggested_sql=suggested_sql,
    )
