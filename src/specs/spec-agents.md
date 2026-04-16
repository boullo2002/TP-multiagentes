# Specification — Two Agents (Schema Agent + Query Agent)

> **Purpose:** Define the responsibilities, prompts, and boundaries for exactly two specialized agents as required by the TP.

---

## 1. Two-agent requirement (strict)

You must implement **exactly two** specialized agents:

1. **Schema Agent**
2. **Query Agent**

They must be clearly separated by:

- responsibilities
- prompts
- tools usage (MCP tool calls)
- graph nodes / grafos compilados

---

## 2. Schema Agent

### 2.1 Responsibilities

- Inspect DB schema metadata via MCP `db_schema_inspect`.
- Analyze the schema and produce a **single context artifact** for downstream NL→SQL:
  - key tables + purpose
  - typical join paths (PK/FK)
  - important columns / time dimensions
  - "gotchas" (ambiguities)
- Trigger HITL when ambiguities exist (preguntas concretas).
- Persist an **approved** artifact under `DATA_DIR/schema_context.json` including al menos:
  - `context_markdown`, `schema_hash`, `table_names`, `schema_catalog`, `questions`, `answers`, `generated_at`, `version`
- Exponer interacción humana por **front dedicado** (Streamlit `schema-ui`, REST `/schema-agent/*`, playground LangServe) independiente del chat del Query Agent.

### 2.2 Inputs

- `schema_metadata` from MCP tool
- existing artifact (if any) from persistent store
- user preferences (language, detail level)
- optional prior human answers to ambiguity questions

### 2.3 Outputs

- `schema_context_draft` (before HITL)
- `schema_context` persisted artifact (after approval / sin preguntas pendientes)

### 2.4 Prompt requirements (in `src/agents/prompts.py`)

Provide:

- a system prompt for the Schema Agent emphasizing:
  - “do not invent columns/relationships”
  - “if ambiguous, ask for confirmation”
  - “write short, query-useful descriptions”
  - Spanish output by default

---

## 3. Query Agent

### 3.1 Responsibilities

- Interpret natural language questions.
- Use **only** (para schema):
  - approved `schema_context` artifact: `context_markdown`, `schema_catalog`, `table_names`
  - **no** MCP schema inspect en el grafo Query
- Usar short-term memory y preferencias de usuario.
- Planner/Executor:
  - Planner: explicit plan
  - Executor: SQL draft (con `retry_feedback` tras validación fallida)
- Critic/Validator antes de ejecutar:
  - safety (read-only, single statement, etc.)
  - auto-fix seguro cuando aplica (p. ej. añadir `LIMIT` en modo strict)
  - **reintentos** internos hasta `QUERY_SQL_RETRY_MAX`; luego bloqueo con mensaje para reformular en NL
- **No** solicitar al usuario final aprobación del SQL.
- Responder intenciones básicas (“capacidades”, “inventario de tablas”) sin generar SQL.
- Execute validated SQL via MCP `db_sql_execute_readonly`.
- Explain results (markdown legible) and support iterative refinement.

### 3.2 Inputs

- user question (chat message)
- `schema_context` (artifact from file)
- `short_term` (last SQL, last filters, assumptions)
- `user_preferences`
- `retry_feedback` (opcional; construido desde `query_retry_issues`)

### 3.3 Outputs

- `query_plan`
- `sql_draft` / `sql_validated`
- `query_result`
- final assistant message including SQL + datos + explanation + limitations

### 3.4 Prompt requirements

Provide:

- a system prompt for Query Agent emphasizing:
  - always produce read-only SQL
  - default LIMIT usage when corresponda
  - explain assumptions
  - ask clarifying questions when necessary (en NL, no pedir editar SQL)
  - Spanish output by default

---

## 4. Planner/Executor (explicit)

Implement as separate functions/classes/modules:

- `src/agents/planner.py`
- `src/agents/query_agent.py` (executor / `draft_sql`)

Planner output must be stored in graph state for traceability.

---

## 5. Critic/Validator (explicit)

Implement in `src/agents/validator.py`:

Input:

- `sql_draft`
- `schema_metadata` (opcional; en el Query graph actual puede ser `None` — la comprobación de tablas se apoya en el artefacto vía SQL coherente con el catálogo)
- safety settings / prefs

Output:

- `is_safe: bool`
- `needs_human_approval: bool` (uso interno / clasificación; **no** implica HITL SQL al usuario en el Query graph)
- `issues: list[str]`
- `suggested_sql: str | None` (auto-fix, p. ej. LIMIT)

---

## 6. Acceptance criteria

- Exactly two agents exist and are used in their respective graphs.
- Planner/Executor separation exists and is visible in code.
- Validator runs before SQL execution in the Query graph, with retry loop wired in the graph.
- Schema Agent persists `schema_context.json` with campos suficientes para NL→SQL sin re-inspeccionar.
- Query Agent reads the artifact and does not rely on runtime `schema_inspect`.
