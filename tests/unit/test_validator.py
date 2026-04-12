from __future__ import annotations

from agents.validator import validate_sql_draft


def test_suggested_sql_adds_limit_in_strict_mode() -> None:
    meta = {"tables": [{"name": "film"}]}
    out = validate_sql_draft(
        "SELECT film_id FROM film",
        schema_metadata=meta,
        user_preferences={"sql_safety_strictness": "strict", "default_limit": 50},
    )
    assert out.is_safe is True
    assert out.needs_human_approval is True
    assert out.suggested_sql == "SELECT film_id FROM film LIMIT 50"


def test_flags_unsafe_sql_ddl() -> None:
    # Given / When
    out = validate_sql_draft(
        "DROP TABLE film;",
        schema_metadata={"tables": [{"name": "film"}]},
        user_preferences={"sql_safety_strictness": "balanced", "default_limit": 50},
    )
    # Then
    assert out.is_safe is False


def test_unknown_table_not_safe() -> None:
    out = validate_sql_draft(
        "SELECT 1 FROM no_existe LIMIT 1",
        schema_metadata={"tables": [{"name": "film"}]},
        user_preferences={"sql_safety_strictness": "balanced", "default_limit": 50},
    )
    assert out.is_safe is False
    assert any("no_existe" in i for i in out.issues)
