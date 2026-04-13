from __future__ import annotations

import pytest

from mcp_server.tools.sql_safety import enforce_readonly


def test_enforce_rejects_dml() -> None:
    with pytest.raises(ValueError, match="no permitidas"):
        enforce_readonly("DELETE FROM film")


def test_enforce_rejects_multiple_statements() -> None:
    with pytest.raises(ValueError, match="múltiples"):
        enforce_readonly("SELECT 1; SELECT 2")


def test_enforce_allows_select_with_limit() -> None:
    enforce_readonly("SELECT 1 FROM film LIMIT 1")


def test_enforce_allows_with_cte() -> None:
    enforce_readonly("WITH x AS (SELECT 1 AS a) SELECT a FROM x LIMIT 1")


def test_enforce_allows_select_after_line_comment() -> None:
    sql = "-- listado\nSELECT table_name FROM information_schema.tables LIMIT 50"
    enforce_readonly(sql)


def test_enforce_allows_select_after_block_comment() -> None:
    sql = "/* meta */ SELECT 1 LIMIT 1"
    enforce_readonly(sql)


def test_enforce_allows_trailing_line_comment_after_semicolon() -> None:
    sql = "SELECT 1 LIMIT 1; -- fin"
    enforce_readonly(sql)


def test_enforce_allows_trailing_block_comment_after_semicolon() -> None:
    sql = "SELECT 1 LIMIT 1; /* fin */"
    enforce_readonly(sql)
