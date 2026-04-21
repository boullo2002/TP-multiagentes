from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_server.server import get_app


def test_tools_list_exposes_catalog() -> None:
    client = TestClient(get_app())
    r = client.get("/tools/list")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("tools"), list)
    names = {t.get("name") for t in body["tools"] if isinstance(t, dict)}
    assert "db_schema_inspect" in names
    assert "db_sql_execute_readonly" in names


def test_tools_call_rejects_unknown_tool() -> None:
    client = TestClient(get_app())
    r = client.post("/tools/call", json={"name": "unknown", "arguments": {}})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "TOOL_NOT_FOUND"


def test_tools_call_rejects_missing_required_argument() -> None:
    client = TestClient(get_app())
    r = client.post(
        "/tools/call",
        json={"name": "db_sql_execute_readonly", "arguments": {"timeout_ms": 1000}},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_ARGUMENTS"
