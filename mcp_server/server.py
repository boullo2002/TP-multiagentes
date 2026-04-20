from __future__ import annotations

import logging
import time
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Request

from mcp_server.tools.schema import inspect_schema
from mcp_server.tools.sql import execute_readonly_sql

logger = logging.getLogger(__name__)

_TOOLS_CATALOG: list[dict[str, Any]] = [
    {
        "name": "db_schema_inspect",
        "description": (
            "Inspecciona el schema PostgreSQL y devuelve tablas, columnas, PK/FK, "
            "índices y constraints."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schema": {
                    "type": ["string", "null"],
                    "description": "Schema a inspeccionar (por defecto: public).",
                },
                "include_views": {
                    "type": "boolean",
                    "description": "Si true, incluye vistas además de tablas base.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "db_sql_execute_readonly",
        "description": (
            "Ejecuta SQL de solo lectura (SELECT/WITH) con guardas de seguridad y "
            "devuelve preview tabular."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Consulta SQL de solo lectura.",
                },
                "timeout_ms": {
                    "type": ["integer", "null"],
                    "description": "Timeout de statement en milisegundos (opcional).",
                    "minimum": 1,
                },
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
]


def _tool_names() -> set[str]:
    return {t["name"] for t in _TOOLS_CATALOG}


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _run_tool(tool_name: str, payload: dict[str, Any], rid: str) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        if tool_name == "db_schema_inspect":
            out = inspect_schema(payload)
            logger.info(
                "mcp_tool tool=%s request_id=%s ok=true elapsed_ms=%s",
                tool_name,
                rid,
                _elapsed_ms(start),
            )
            return out
        if tool_name == "db_sql_execute_readonly":
            out = execute_readonly_sql(payload)
            logger.info(
                "mcp_tool tool=%s request_id=%s ok=true elapsed_ms=%s row_count=%s",
                tool_name,
                rid,
                _elapsed_ms(start),
                out.get("row_count"),
            )
            return out
        raise HTTPException(
            status_code=404,
            detail={
                "error": True,
                "code": "TOOL_NOT_FOUND",
                "message": f"Herramienta desconocida: {tool_name}",
            },
        )
    except ValueError as e:
        logger.info(
            "mcp_tool tool=%s request_id=%s ok=false err=sql_rejected elapsed_ms=%s detail=%s",
            tool_name,
            rid,
            _elapsed_ms(start),
            e,
        )
        raise HTTPException(
            status_code=400,
            detail={"error": True, "code": "SQL_REJECTED", "message": str(e)},
        ) from e
    except psycopg.OperationalError as e:
        logger.exception(
            "mcp_tool tool=%s request_id=%s ok=false err=db_unreachable",
            tool_name,
            rid,
        )
        raise HTTPException(
            status_code=503,
            detail={"error": True, "code": "DB_UNREACHABLE", "message": str(e)},
        ) from e
    except psycopg.Error as e:
        logger.exception("mcp_tool tool=%s request_id=%s ok=false err=db", tool_name, rid)
        raise HTTPException(
            status_code=400,
            detail={"error": True, "code": "DB_ERROR", "message": str(e)},
        ) from e
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("mcp_tool tool=%s request_id=%s ok=false", tool_name, rid)
        raise HTTPException(
            status_code=500,
            detail={"error": True, "code": "INTERNAL", "message": str(e)},
        ) from e


def get_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "healthy"}

    @app.get("/tools/list")
    def tools_list() -> dict[str, Any]:
        # Contrato estilo MCP para discovery de herramientas.
        return {"tools": _TOOLS_CATALOG}

    @app.post("/tools/call")
    def tools_call(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        rid = request.headers.get("x-request-id") or "-"
        tool_name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments")
        if not tool_name:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": True,
                    "code": "BAD_REQUEST",
                    "message": "Falta el campo `name`.",
                },
            )
        if not isinstance(arguments, dict):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": True,
                    "code": "BAD_REQUEST",
                    "message": "`arguments` debe ser un objeto JSON.",
                },
            )
        if tool_name not in _tool_names():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": True,
                    "code": "TOOL_NOT_FOUND",
                    "message": f"Herramienta desconocida: {tool_name}",
                },
            )
        return _run_tool(tool_name, arguments, rid)

    return app
