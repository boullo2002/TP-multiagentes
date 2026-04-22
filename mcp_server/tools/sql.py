from __future__ import annotations

import os
import time
from typing import Any

import psycopg

from mcp_server.tools.sql_safety import enforce_readonly


def execute_readonly_sql(payload: dict[str, Any]) -> dict[str, Any]:
    sql = payload.get("sql") or ""
    timeout_ms = payload.get("timeout_ms")
    raw_max = payload.get("result_max_rows")
    if raw_max is None:
        max_rows = 50
    else:
        try:
            max_rows = int(raw_max)
        except (TypeError, ValueError) as e:
            raise ValueError("result_max_rows debe ser un entero.") from e
    max_rows = max(1, min(max_rows, 10_000))
    enforce_readonly(sql)

    dsn = os.environ["DATABASE_URL"]
    start = time.perf_counter()
    with psycopg.connect(dsn) as conn:
        if timeout_ms is not None:
            ms = int(timeout_ms)
            if ms <= 0:
                raise ValueError("timeout_ms debe ser un entero positivo.")
            # SET no admite placeholders ($1); el valor debe ser literal en el comando.
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {ms}")
        with conn.cursor() as cur:
            cur.execute(sql)
            chunk = cur.fetchmany(max_rows + 1)
            truncated = len(chunk) > max_rows
            rows = chunk[:max_rows]
            cols = [d.name for d in cur.description] if cur.description else []
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "execution_ms": elapsed_ms,
        "truncated": truncated,
        "result_max_rows": max_rows,
    }
