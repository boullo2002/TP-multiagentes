from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Fallo al invocar el servidor MCP (red, timeout o respuesta HTTP de error)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _sanitize_payload_for_log(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "db_sql_execute_readonly":
        sql = payload.get("sql") or ""
        preview = sql if len(sql) <= 240 else sql[:240] + "…"
        return {
            "sql_preview": preview,
            "timeout_ms": payload.get("timeout_ms"),
        }
    if tool_name == "db_schema_inspect":
        return {
            "schema": payload.get("schema"),
            "include_views": payload.get("include_views"),
        }
    return {k: payload[k] for k in sorted(payload.keys())[:20]}


def _result_summary(tool_name: str, data: dict[str, Any]) -> str:
    if tool_name == "db_schema_inspect":
        n = len(data.get("tables") or [])
        return f"tables={n}"
    if tool_name == "db_sql_execute_readonly":
        return (
            f"row_count={data.get('row_count')} cols={len(data.get('columns') or [])} "
            f"execution_ms={data.get('execution_ms')}"
        )
    return "ok"


def _http_exception_message(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except Exception:  # noqa: BLE001
        return exc.response.text or str(exc)
    if isinstance(body, dict) and "detail" in body:
        d = body["detail"]
        if isinstance(d, dict):
            return str(d.get("message", d))
        return str(d)
    return str(body)


class MCPClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.mcp.server_url.rstrip("/")
        self._timeout = httpx.Timeout(settings.mcp.request_timeout_ms / 1000.0)
        self._tools_cache: dict[str, dict[str, Any]] | None = None

    def list_tools(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if self._tools_cache is not None and not refresh:
            return list(self._tools_cache.values())
        request_id = uuid.uuid4().hex[:16]
        url = f"{self._base_url}/tools/list"
        headers = {"X-Request-ID": request_id}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        tools = body.get("tools") if isinstance(body, dict) else None
        if not isinstance(tools, list):
            raise MCPClientError(
                "MCP tools/list devolvio un payload invalido.",
                status_code=500,
                detail=body,
            )
        indexed: dict[str, dict[str, Any]] = {}
        for t in tools:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                indexed[t["name"]] = t
        self._tools_cache = indexed
        return list(indexed.values())

    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        call_url = f"{self._base_url}/tools/call"
        request_id = uuid.uuid4().hex[:16]
        headers = {"X-Request-ID": request_id}
        safe = _sanitize_payload_for_log(tool_name, payload)
        logger.info(
            "mcp_call_start tool=%s request_id=%s payload=%s",
            tool_name,
            request_id,
            safe,
        )
        if self._tools_cache is None:
            self.list_tools()
        if self._tools_cache is not None and tool_name not in self._tools_cache:
            raise MCPClientError(
                f"La herramienta `{tool_name}` no fue publicada por tools/list.",
                status_code=404,
                detail={"tool_name": tool_name},
            )
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    call_url,
                    json={"name": tool_name, "arguments": payload},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            msg = _http_exception_message(e)
            detail: Any = None
            try:
                detail = e.response.json() if e.response is not None else None
            except Exception:  # noqa: BLE001
                detail = e.response.text if e.response is not None else None
            logger.warning(
                "mcp_call_error tool=%s request_id=%s status=%s elapsed_ms=%s msg=%s",
                tool_name,
                request_id,
                e.response.status_code if e.response else None,
                elapsed_ms,
                msg[:500],
            )
            raise MCPClientError(
                f"MCP {tool_name} falló ({e.response.status_code if e.response else '?'}): {msg}",
                status_code=e.response.status_code if e.response else None,
                detail=detail,
            ) from e
        except httpx.RequestError as e:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                "mcp_call_error tool=%s request_id=%s elapsed_ms=%s transport=%s",
                tool_name,
                request_id,
                elapsed_ms,
                e,
            )
            raise MCPClientError(
                f"No se pudo conectar al servidor MCP ({tool_name}): {e}",
                status_code=None,
                detail=None,
            ) from e

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "mcp_call_ok tool=%s request_id=%s elapsed_ms=%s result=%s",
            tool_name,
            request_id,
            elapsed_ms,
            _result_summary(tool_name, data),
        )
        return data
