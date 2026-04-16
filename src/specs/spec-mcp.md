# Specification — MCP Server + Tools (Schema inspection + Read-only SQL execution)

> **Purpose:** Define the MCP requirement for the TP: implement an MCP server (separate docker service) and use it from LangGraph nodes for schema inspection and read-only SQL execution.

---

## 1. Scope

- Implement an MCP server under `mcp_server/` exposing at least:
  - `db_schema_inspect`
  - `db_sql_execute_readonly`
- The FastAPI app must act as an MCP client via `src/tools/mcp_client.py`.
- All MCP tool calls must be:
  - invoked from graph nodes
  - logged (tool name, inputs sanitized, duration, result/error)

---

## 2. Tool: `db_schema_inspect`

### 2.1 Purpose

Return PostgreSQL schema metadata for DVD Rental:

- tables
- columns (name, type, nullable, default)
- primary keys
- foreign keys (column, referenced table/column)
- optionally indexes and constraints if easy

### 2.2 Input

- `schema: str | null` (default: public)
- `include_views: bool` (default: false)

### 2.3 Output (minimum)

```json
{
  "tables": [
    {
      "name": "film",
      "columns": [
        { "name": "film_id", "type": "integer", "nullable": false, "default": null }
      ],
      "primary_key": ["film_id"],
      "foreign_keys": [
        { "column": "language_id", "ref_table": "language", "ref_column": "language_id" }
      ]
    }
  ]
}
```

### 2.4 Errors

- If DB is unreachable: return a structured error and log it.

---

## 3. Tool: `db_sql_execute_readonly`

### 3.1 Purpose

Execute **read-only** SQL and return a preview of results.

### 3.2 Input

- `sql: str`
- `timeout_ms: int | null`

### 3.3 Output (minimum)

```json
{
  "columns": ["title", "rental_count"],
  "rows": [["ACADEMY DINOSAUR", 23]],
  "row_count": 1,
  "execution_ms": 12
}
```

### 3.4 Safety rules (must enforce)

This tool must refuse execution if SQL is not safe/read-only. Minimum checks:

- no `INSERT/UPDATE/DELETE/ALTER/DROP/TRUNCATE/CREATE`
- no multiple statements (tras el último `;` solo comentarios/espacios permitidos; comentarios iniciales antes de `SELECT`/`WITH` permitidos)
- allow only `SELECT` (CTEs allowed if they are part of a SELECT)

**Note:** The backend also has a validator. This tool must still re-check safety as defense in depth.

**Implementación:** al fijar `statement_timeout` en Postgres, usar valor literal en el comando `SET` (no parámetros preparados), validando que el timeout sea positivo.

---

## 4. MCP server implementation notes

### 4.1 Runtime

The MCP server is a separate process/container:

- service name `mcp` in docker-compose
- environment includes `DATABASE_URL` pointing to `db`

### 4.2 Database access

Use a standard PostgreSQL driver (`psycopg` recommended) inside the MCP server.

### 4.3 Observability

Log each tool call:

- tool name
- request id (if available)
- duration
- ok/error

---

## 5. Backend MCP client requirements (`src/tools/mcp_client.py`)

Implement a small client with:

- `call_tool(tool_name: str, payload: dict) -> dict`
- request timeout from env
- clear errors on connection failure

---

## 6. Acceptance criteria

1. MCP server runs as a docker service and connects to the DVD Rental DB.
2. `db_schema_inspect` returns metadata.
3. `db_sql_execute_readonly` executes safe SELECTs and rejects unsafe SQL.
4. The LangGraph workflow calls these tools from nodes, and calls are logged.

