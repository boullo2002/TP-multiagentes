# Specification — LangGraph Workflow (Two-Agent System)

> **Purpose:** Define the LangGraph StateGraph orchestration for the TP: explicit state, nodes, edges, routing, HITL solo en Schema Agent, validador + reintentos en Query Agent.

---

## 1. Purpose and scope

- **Purpose**: Implement a **two-agent** multi-agent workflow en **dos grafos compilados**:
  - **Schema graph**: inspección MCP → borrador de contexto → HITL si hay ambigüedad → persistencia de `schema_context.json`
  - **Query graph**: carga del artefacto → intenciones básicas (sin SQL) → planner → SQL → validador (con **retry**) → ejecución MCP → explicación + memoria corta
- **Scope**:
  - Query Agent expuesto vía LangServe `/tp-agent` y `POST /v1/chat/completions`
  - Schema Agent expuesto vía LangServe `/schema-agent` y endpoints REST/UI en `main.py`

---

## 2. State schema (`src/graph/state.py`)

Implement a single `GraphState` (TypedDict with `total=False`) containing at least:

- `messages`: `Annotated[list[AnyMessage], add_messages]`
- `mode`: `Literal["query", "schema", "schema_hitl_resume"]`
- `session_id`: `str`
- `user_preferences`: `dict`

### 2.1 Schema artifacts

- `schema_metadata`: dict (rellenado en flujo Schema al inspeccionar; el Query graph no depende de inspección en runtime)
- `schema_context`: dict (artefacto cargado desde `schema_context.json`)
- `schema_context_draft`: dict (borrador + preguntas HITL)
- `schema_context_answers`: dict (respuestas humanas)
- `schema_hitl_pending`: bool

### 2.2 Query artifacts

- `query_plan`: dict | str
- `sql_draft`: str
- `sql_validated`: str
- `sql_validation`: dict serializable (p. ej. issues, flags del validador)
- `query_retry_count`: int
- `query_retry_pending`: bool
- `query_retry_issues`: list[str]
- `query_blocked`: bool (fin temprano o error al usuario)
- `query_result`: dict (columns, rows, row_count, execution_ms)
- `last_error`: str (opcional; sin `None` en el tipo para JSON Schema / LangServe playground)

### 2.3 Short-term memory snapshot

- `short_term`: dict (last_sql, last_filters, recent_tables, open_assumptions, etc.)

---

## 3. Nodes (required)

Implement the graphs in:

- `src/graph/query_workflow.py`
- `src/graph/schema_workflow.py`

### 3.1 Query graph: `router`

Fija `mode="query"` y enruta siempre al flujo de consulta (no hay router global schema/query en el mismo grafo).

### 3.2 Schema graph nodes

- `schema_load` — hidrata prefs + `schema_context` existente desde disco
- `schema_inspect_initial` / `schema_inspect_resume` — MCP `db_schema_inspect` (misma función nodo, dos entradas según camino)
- `schema_draft` — `SchemaAgent.draft_context`: markdown + preguntas + hash
- `schema_hitl_resume_loader` — parsea mensaje/respuestas del usuario (`APPROVE` o JSON de respuestas)
- `schema_redraft` — rearma contexto con respuestas
- `schema_persist` — escribe `DATA_DIR/schema_context.json` (markdown, hash, `table_names`, `schema_catalog`, Q/A)

### 3.3 Query flow nodes

- `query_load` (`query_load_context`)
  - prefs + `schema_context` desde `SchemaContextStore`
  - si falta contexto o regeneración requiere HITL: mensaje al usuario y `query_blocked` (derivación a `/schema-agent/ui`)
  - resetea `query_retry_*` y `query_blocked` en el camino feliz
- `query_basic` (`query_basic_intents`)
  - “qué podés hacer” / “qué tablas hay”: responde desde conocimiento fijo + `schema_context` (`table_names` / `schema_catalog`); pone `query_blocked=True` y termina
- `query_plan` — planner explícito
- `query_sql` — `QueryAgent.draft_sql` con `retry_feedback` si hubo intentos fallidos
- `query_validate` — `validate_sql_draft`; aplica `suggested_sql` (p. ej. LIMIT); si inseguro, **retry** hasta `QUERY_SQL_RETRY_MAX`; si agota, mensaje de reformulación
- `query_execute` — MCP `db_sql_execute_readonly`
- `query_explain` — respuesta final (SQL en bloque, métricas, tabla markdown de filas)
- `query_mem` — actualiza `short_term` + `SessionStore`

---

## 4. Edges and routing

### 4.1 Query graph

`START -> router -> query_load -> query_basic`

Desde `query_basic`, condicional `route_after_query_validator`:

- si `query_blocked`: `END` (respuesta ya en mensajes)
- si no: `query_plan`

Luego:

`query_plan -> query_sql -> query_validate`

Desde `query_validate`, condicional:

- `retry` → `query_sql`
- `end` → `END`
- `execute` → `query_execute`

`query_execute -> query_explain -> query_mem -> END`

### 4.2 Schema graph

`START -> router` → (`schema_hitl_resume` → `schema_hitl_resume_loader` | `schema` → `schema_load`)

`schema_load -> schema_inspect_initial -> schema_draft`

Desde `schema_draft`:

- si `schema_hitl_pending`: `END` (mensaje con checkpoint)
- si no: `schema_persist -> END`

Resume:

`schema_hitl_resume_loader -> schema_inspect_resume -> schema_redraft` → misma condicional HITL/persist.

---

## 5. HITL checkpoints

- **Schema Agent**: ambigüedades de negocio/schema; tokens `HITL_CHECKPOINT_ID`, `HITL_KIND=schema_context`; respuestas vía chat del playground, `/schema-agent/answer`, Streamlit `schema-ui`, o `/schema-agent/ui`.
- **Query Agent**: **no** pide aprobación humana para ejecutar SQL; el usuario final reformula en lenguaje natural si el sistema bloquea tras reintentos.

---

## 6. Acceptance criteria

- Dos grafos compilados con nodos/aristas explícitos y estado estable.
- Schema flow genera borrador, puede pausar en HITL, persiste artefacto completo para el Query Agent.
- Query flow usa planner + SQL + validador con **reintentos acotados**, ejecuta vía MCP, devuelve SQL + resultado legible + límites.
- Transiciones y llamadas a herramientas quedan registradas en logs.
