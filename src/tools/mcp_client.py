from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.mcp.server_url.rstrip("/")
        self._timeout = httpx.Timeout(settings.mcp.request_timeout_ms / 1000.0)

    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/tools/{tool_name}"
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info("mcp_tool_ok tool=%s elapsed_ms=%s", tool_name, elapsed_ms)
            return data
        except Exception as e:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "mcp_tool_error tool=%s elapsed_ms=%s err=%s", tool_name, elapsed_ms, e
            )
            raise
