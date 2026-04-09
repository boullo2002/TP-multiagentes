from __future__ import annotations

from tools.sql_safety import validate_sql


def test_blocks_ddl_dml_keywords() -> None:
    res = validate_sql("DROP TABLE film;")
    assert res.ok is False


def test_blocks_multiple_statements() -> None:
    res = validate_sql("SELECT 1; SELECT 2;")
    assert res.ok is False


def test_allows_select() -> None:
    res = validate_sql("SELECT 1 LIMIT 1")
    assert res.ok is True


def test_requires_limit_in_strict_mode_requests_hitl() -> None:
    res = validate_sql("SELECT 1", strictness="strict")
    assert res.ok is True
    assert res.needs_human_approval is True
