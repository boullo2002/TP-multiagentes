from __future__ import annotations

from typing import Any

# spec-memory.md §1.1 (valores fijos por defecto; strict/limit se alinean con env al normalizar)
DEFAULT_USER_PREFERENCES: dict[str, Any] = {
    "preferred_language": "es",
    "preferred_output_format": "table",
    "preferred_date_format": "YYYY-MM-DD",
    "sql_safety_strictness": "strict",
    "default_limit": 50,
}


def _coerce_pref_dict(base: dict[str, Any]) -> dict[str, Any]:
    fmt = base.get("preferred_output_format", "table")
    if fmt not in ("table", "json"):
        base["preferred_output_format"] = "table"
    strict = base.get("sql_safety_strictness", "strict")
    if strict not in ("strict", "balanced"):
        base["sql_safety_strictness"] = "strict"
    try:
        base["default_limit"] = max(1, min(10_000, int(base.get("default_limit", 50))))
    except (TypeError, ValueError):
        base["default_limit"] = 50
    return base


def normalize_user_preferences(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Mergea con defaults; strictness y default_limit parten del env si no hay archivo."""
    from config.settings import get_settings

    s = get_settings()
    base = dict(DEFAULT_USER_PREFERENCES)
    base["sql_safety_strictness"] = s.safety.sql_safety_strictness
    base["default_limit"] = s.safety.default_limit
    if not raw:
        return _coerce_pref_dict(base)
    base.update(raw)
    if raw.get("language") and "preferred_language" not in raw:
        base["preferred_language"] = raw["language"]
    if raw.get("output_format") and "preferred_output_format" not in raw:
        base["preferred_output_format"] = raw["output_format"]
    return _coerce_pref_dict(base)


def prefs_for_prompts(prefs: dict[str, Any]) -> dict[str, Any]:
    """Claves cómodas para prompts (idioma, formato, fecha, límites)."""
    p = normalize_user_preferences(prefs)
    return {
        "language": p["preferred_language"],
        "output_format": p["preferred_output_format"],
        "date_format": p["preferred_date_format"],
        "sql_safety_strictness": p["sql_safety_strictness"],
        "default_limit": p["default_limit"],
    }
