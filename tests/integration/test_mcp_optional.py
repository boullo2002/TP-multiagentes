from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def mcp_base() -> str:
    return os.getenv("MCP_SERVER_URL", "http://127.0.0.1:7000").rstrip("/")


def test_mcp_health_when_available(mcp_base) -> None:
    # Given / When: servicio MCP levantado (spec-tests §5 opcional)
    if os.getenv("RUN_MCP_INTEGRATION") != "1":
        pytest.skip("Definí RUN_MCP_INTEGRATION=1 para correr contra MCP real.")
    try:
        r = httpx.get(f"{mcp_base}/health", timeout=3.0)
    except httpx.RequestError:
        pytest.skip(f"MCP no alcanzable en {mcp_base}")
    assert r.status_code == 200


def test_mcp_tools_list_when_available(mcp_base) -> None:
    if os.getenv("RUN_MCP_INTEGRATION") != "1":
        pytest.skip("Definí RUN_MCP_INTEGRATION=1 para correr contra MCP real.")
    try:
        r = httpx.get(f"{mcp_base}/tools/list", timeout=10.0)
    except httpx.RequestError:
        pytest.skip("MCP no alcanzable")
    assert r.status_code == 200
    body = r.json()
    assert "tools" in body
    assert isinstance(body["tools"], list)


def test_mcp_schema_inspect_returns_tables_key(mcp_base) -> None:
    if os.getenv("RUN_MCP_INTEGRATION") != "1":
        pytest.skip("Definí RUN_MCP_INTEGRATION=1 para correr contra MCP real.")
    try:
        r = httpx.post(
            f"{mcp_base}/tools/call",
            json={
                "name": "db_schema_inspect",
                "arguments": {"schema": "public", "include_views": False},
            },
            timeout=30.0,
        )
    except httpx.RequestError:
        pytest.skip("MCP no alcanzable")
    assert r.status_code == 200
    body = r.json()
    assert "tables" in body
    assert isinstance(body["tables"], list)


def test_mcp_sql_readonly_returns_rows(mcp_base) -> None:
    if os.getenv("RUN_MCP_INTEGRATION") != "1":
        pytest.skip("Definí RUN_MCP_INTEGRATION=1 para correr contra MCP real.")
    try:
        r = httpx.post(
            f"{mcp_base}/tools/call",
            json={
                "name": "db_sql_execute_readonly",
                "arguments": {"sql": "SELECT 1 AS one LIMIT 1", "timeout_ms": 5000},
            },
            timeout=30.0,
        )
    except httpx.RequestError:
        pytest.skip("MCP no alcanzable")
    assert r.status_code == 200
    data = r.json()
    assert "rows" in data
    assert "columns" in data
