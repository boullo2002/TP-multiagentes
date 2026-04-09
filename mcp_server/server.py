from __future__ import annotations

import logging
import time
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException

from mcp_server.tools.schema import inspect_schema
from mcp_server.tools.sql import execute_readonly_sql

logger = logging.getLogger(__name__)


def get_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "healthy"}

    @app.post("/tools/db_schema_inspect")
    def tool_schema_inspect(payload: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            return inspect_schema(payload)
        except Exception as e:  # noqa: BLE001
            logger.exception("tool=db_schema_inspect err=%s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e
        finally:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info("tool=db_schema_inspect elapsed_ms=%s", elapsed_ms)

    @app.post("/tools/db_sql_execute_readonly")
    def tool_sql_execute(payload: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            return execute_readonly_sql(payload)
        except psycopg.Error as e:
            logger.exception("tool=db_sql_execute_readonly db_err=%s", e)
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("tool=db_sql_execute_readonly err=%s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e
        finally:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info("tool=db_sql_execute_readonly elapsed_ms=%s", elapsed_ms)

    return app
