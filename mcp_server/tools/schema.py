from __future__ import annotations

import os
from typing import Any

import psycopg


def inspect_schema(payload: dict[str, Any]) -> dict[str, Any]:
    schema = payload.get("schema") or "public"
    dsn = os.environ["DATABASE_URL"]
    tables: list[dict[str, Any]] = []

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
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
                    {"column": r[0], "ref_table": r[1], "ref_column": r[2]} for r in cur.fetchall()
                ]

                tables.append({"name": t, "columns": cols, "primary_key": pk, "foreign_keys": fks})

    return {"tables": tables}
