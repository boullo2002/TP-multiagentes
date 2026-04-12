from __future__ import annotations

import logging
import os
from typing import Any

import psycopg

logger = logging.getLogger(__name__)


def _fetch_indexes(cur: Any, schema: str, table: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = %s AND tablename = %s
        ORDER BY indexname
        """,
        (schema, table),
    )
    return [{"name": r[0], "definition": r[1]} for r in cur.fetchall()]


def _fetch_unique_constraints(cur: Any, schema: str, table: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT tc.constraint_name, kcu.column_name, kcu.ordinal_position
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_schema = kcu.constraint_schema
         AND tc.constraint_name = kcu.constraint_name
        WHERE tc.table_schema = %s
          AND tc.table_name = %s
          AND tc.constraint_type = 'UNIQUE'
        ORDER BY tc.constraint_name, kcu.ordinal_position
        """,
        (schema, table),
    )
    rows = cur.fetchall()
    by_name: dict[str, list[str]] = {}
    for name, col, _pos in rows:
        by_name.setdefault(name, []).append(col)
    return [{"name": n, "columns": cols} for n, cols in sorted(by_name.items())]


def inspect_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Metadata de tablas/vistas: columnas, PK, FK, índices, UNIQUE (spec-mcp §2).
    """
    schema = payload.get("schema") or "public"
    include_views = bool(payload.get("include_views"))
    dsn = os.environ["DATABASE_URL"]
    tables: list[dict[str, Any]] = []

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                if include_views:
                    cur.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = %s
                          AND table_type IN ('BASE TABLE', 'VIEW')
                        ORDER BY table_name
                        """,
                        (schema,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = %s AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """,
                        (schema,),
                    )
                table_names = [r[0] for r in cur.fetchall()]

                for t in table_names:
                    cur.execute(
                        """
                        SELECT column_name, data_type, is_nullable, column_default
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (schema, t),
                    )
                    cols = [
                        {
                            "name": r[0],
                            "type": r[1],
                            "nullable": (r[2] == "YES"),
                            "default": r[3],
                        }
                        for r in cur.fetchall()
                    ]

                    cur.execute(
                        """
                        SELECT kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_schema = kcu.table_schema
                        WHERE tc.table_schema = %s
                          AND tc.table_name = %s
                          AND tc.constraint_type = 'PRIMARY KEY'
                        ORDER BY kcu.ordinal_position
                        """,
                        (schema, t),
                    )
                    pk = [r[0] for r in cur.fetchall()]

                    cur.execute(
                        """
                        SELECT kcu.column_name, ccu.table_name, ccu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_schema = kcu.table_schema
                        JOIN information_schema.constraint_column_usage ccu
                          ON ccu.constraint_name = tc.constraint_name
                         AND ccu.table_schema = tc.table_schema
                        WHERE tc.table_schema = %s
                          AND tc.table_name = %s
                          AND tc.constraint_type = 'FOREIGN KEY'
                        ORDER BY kcu.ordinal_position
                        """,
                        (schema, t),
                    )
                    fks = [
                        {"column": r[0], "ref_table": r[1], "ref_column": r[2]}
                        for r in cur.fetchall()
                    ]

                    indexes = _fetch_indexes(cur, schema, t)
                    unique_constraints = _fetch_unique_constraints(cur, schema, t)

                    tables.append(
                        {
                            "name": t,
                            "columns": cols,
                            "primary_key": pk,
                            "foreign_keys": fks,
                            "indexes": indexes,
                            "unique_constraints": unique_constraints,
                        }
                    )
    except psycopg.OperationalError:
        logger.exception("inspect_schema DB unreachable schema=%s", schema)
        raise
    except psycopg.Error:
        logger.exception("inspect_schema DB error schema=%s", schema)
        raise

    return {"tables": tables}
