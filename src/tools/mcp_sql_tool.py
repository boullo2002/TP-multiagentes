from __future__ import annotations

from typing import Any

from tools.mcp_client import MCPClient


def sql_execute_readonly(*, sql: str, timeout_ms: int | None = None) -> dict[str, Any]:
    client = MCPClient()
    return client.call_tool("db_sql_execute_readonly", {"sql": sql, "timeout_ms": timeout_ms})
