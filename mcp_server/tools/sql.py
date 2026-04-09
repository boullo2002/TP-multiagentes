from __future__ import annotations

import os
import time
from typing import Any

import psycopg

from mcp_server.tools.sql_safety import enforce_readonly


def execute_readonly_sql(payload: dict[str, Any]) -> dict[str, Any]:
    sql = payload.get("sql") or ""
    timeout_ms = payload.get("timeout_ms")
    enforce_readonly(sql)

    dsn = os.environ["DATABASE_URL"]
    start = time.perf_counter()
    with psycopg.connect(dsn) as conn:
        if timeout_ms:
            with conn.cursor() as c2:
                c2.execute("SET statement_timeout = %s", (int(timeout_ms),))
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchmany(50)
            cols = [d.name for d in cur.description] if cur.description else []
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {"columns": cols, "rows": rows, "row_count": len(rows), "execution_ms": elapsed_ms}
