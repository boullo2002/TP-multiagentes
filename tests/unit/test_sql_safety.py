from __future__ import annotations

from tools.sql_safety import validate_sql


def test_blocks_ddl_dml_keywords() -> None:
    # Given / When
    res = validate_sql("DROP TABLE film;")
    # Then
    assert res.ok is False


def test_blocks_multiple_statements() -> None:
    # Given / When
    res = validate_sql("SELECT 1; SELECT 2;")
    # Then
    assert res.ok is False


def test_allows_select_with_limit() -> None:
    # Given / When
    res = validate_sql("SELECT 1 LIMIT 1")
    # Then
    assert res.ok is True


def test_allows_trailing_comment_after_semicolon() -> None:
    res = validate_sql(
        "SELECT 1 LIMIT 1; -- comentario al final",
        strictness="balanced",
    )
    assert res.ok is True


def test_allows_select_after_leading_line_comment() -> None:
    res = validate_sql(
        "-- tablas\nSELECT table_name FROM information_schema.tables LIMIT 50",
        strictness="balanced",
    )
    assert res.ok is True


def test_requires_limit_in_strict_mode_requests_hitl() -> None:
    # Given / When (strict sin LIMIT → revisión humana)
    res = validate_sql("SELECT 1", strictness="strict")
    # Then
    assert res.ok is True
    assert res.needs_human_approval is True
