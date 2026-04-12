from __future__ import annotations

import logging
import time
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Request

from mcp_server.tools.schema import inspect_schema
from mcp_server.tools.sql import execute_readonly_sql

logger = logging.getLogger(__name__)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def get_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "healthy"}

    @app.post("/tools/db_schema_inspect")
    def tool_schema_inspect(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        rid = request.headers.get("x-request-id") or "-"
        start = time.perf_counter()
        try:
            out = inspect_schema(payload)
            logger.info(
                "mcp_tool tool=db_schema_inspect request_id=%s ok=true elapsed_ms=%s",
                rid,
                _elapsed_ms(start),
            )
            return out
        except psycopg.OperationalError as e:
            logger.exception(
                "mcp_tool tool=db_schema_inspect request_id=%s ok=false err=db_unreachable",
                rid,
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "error": True,
                    "code": "DB_UNREACHABLE",
                    "message": str(e),
                },
            ) from e
        except psycopg.Error as e:
            logger.exception("mcp_tool tool=db_schema_inspect request_id=%s ok=false err=db", rid)
            raise HTTPException(
                status_code=500,
                detail={"error": True, "code": "DB_ERROR", "message": str(e)},
            ) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("mcp_tool tool=db_schema_inspect request_id=%s ok=false", rid)
            raise HTTPException(
                status_code=500,
                detail={"error": True, "code": "INTERNAL", "message": str(e)},
            ) from e

    @app.post("/tools/db_sql_execute_readonly")
    def tool_sql_execute(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        rid = request.headers.get("x-request-id") or "-"
        start = time.perf_counter()
        try:
            out = execute_readonly_sql(payload)
            logger.info(
                "mcp_tool tool=db_sql_execute_readonly request_id=%s ok=true elapsed_ms=%s "
                "row_count=%s",
                rid,
                _elapsed_ms(start),
                out.get("row_count"),
            )
            return out
        except ValueError as e:
            logger.info(
                "mcp_tool tool=db_sql_execute_readonly request_id=%s ok=false err=sql_rejected "
                "elapsed_ms=%s detail=%s",
                rid,
                _elapsed_ms(start),
                e,
            )
            raise HTTPException(
                status_code=400,
                detail={"error": True, "code": "SQL_REJECTED", "message": str(e)},
            ) from e
        except psycopg.Error as e:
            logger.exception("mcp_tool tool=db_sql_execute_readonly request_id=%s ok=false db", rid)
            raise HTTPException(
                status_code=400,
                detail={"error": True, "code": "DB_ERROR", "message": str(e)},
            ) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("mcp_tool tool=db_sql_execute_readonly request_id=%s ok=false", rid)
            raise HTTPException(
                status_code=500,
                detail={"error": True, "code": "INTERNAL", "message": str(e)},
            ) from e

    return app
