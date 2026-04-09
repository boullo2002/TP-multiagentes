from __future__ import annotations

from typing import Any

from tools.mcp_client import MCPClient


def schema_inspect(*, schema: str | None = None, include_views: bool = False) -> dict[str, Any]:
    client = MCPClient()
    return client.call_tool(
        "db_schema_inspect",
        {"schema": schema, "include_views": include_views},
    )
