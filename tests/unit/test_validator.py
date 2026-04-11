from __future__ import annotations

from agents.validator import validate_sql_draft


def _fake_settings(*, strict: str, limit: int):
    class S:
        class safety:
            sql_safety_strictness = strict
            default_limit = limit

    return S()


def test_suggested_sql_adds_limit_in_strict_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "agents.validator.get_settings",
        lambda: _fake_settings(strict="strict", limit=50),
    )
    meta = {"tables": [{"name": "film"}]}
    out = validate_sql_draft("SELECT film_id FROM film", schema_metadata=meta)
    assert out.is_safe is True
    assert out.needs_human_approval is True
    assert out.suggested_sql == "SELECT film_id FROM film LIMIT 50"


def test_unknown_table_not_safe(monkeypatch) -> None:
    monkeypatch.setattr(
        "agents.validator.get_settings",
        lambda: _fake_settings(strict="balanced", limit=50),
    )
    out = validate_sql_draft(
        "SELECT 1 FROM no_existe LIMIT 1",
        schema_metadata={"tables": [{"name": "film"}]},
    )
    assert out.is_safe is False
    assert any("no_existe" in i for i in out.issues)
