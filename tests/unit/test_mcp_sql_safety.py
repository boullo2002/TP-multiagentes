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
