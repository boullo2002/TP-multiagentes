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


def _tool_by_name(name: str) -> dict[str, Any] | None:
    for t in _TOOLS_CATALOG:
        if t["name"] == name:
            return t
    return None


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    tool = _tool_by_name(tool_name)
    if not tool:
        raise HTTPException(
            status_code=404,
            detail={
                "error": True,
                "code": "TOOL_NOT_FOUND",
                "message": f"Herramienta desconocida: {tool_name}",
            },
        )
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        return
    props = schema.get("properties")
    required = schema.get("required") or []
    if not isinstance(props, dict):
        props = {}

    for k in required:
        if k not in arguments:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": True,
                    "code": "BAD_ARGUMENTS",
                    "message": f"Falta argumento requerido: {k}",
                },
            )

    if schema.get("additionalProperties") is False:
        extra = [k for k in arguments if k not in props]
        if extra:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": True,
                    "code": "BAD_ARGUMENTS",
                    "message": f"Argumentos no permitidos: {', '.join(extra)}",
                },
            )

    for key, value in arguments.items():
        p = props.get(key)
        if not isinstance(p, dict):
            continue
        typ = p.get("type")
        allowed = typ if isinstance(typ, list) else [typ] if isinstance(typ, str) else []
        if allowed and not any(_type_ok(value, t) for t in allowed):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": True,
                    "code": "BAD_ARGUMENTS",
                    "message": f"Tipo inválido para `{key}`.",
                },
            )
        if "minimum" in p and isinstance(value, int) and value < int(p["minimum"]):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": True,
                    "code": "BAD_ARGUMENTS",
                    "message": f"`{key}` debe ser >= {p['minimum']}.",
                },
            )


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
        _validate_arguments(tool_name, arguments)
        return _run_tool(tool_name, arguments, rid)

    return app
