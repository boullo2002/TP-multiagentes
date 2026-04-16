# Specification — LangGraph Workflow (Two-Agent System)

> **Purpose:** Define the LangGraph StateGraph orchestration for the TP: explicit state, nodes, edges, routing, HITL checkpoints, and validator step.

---

## 1. Purpose and scope

- **Purpose**: Implement a **two-agent** multi-agent workflow in LangGraph:
  - Schema Agent flow for schema context generation + approvals
  - Query Agent flow for NL→SQL + validation + safe execution + explanation
- **Scope**:
  - Two compiled graphs (independent UIs):
    - Query Agent runnable route (LangServe + OpenAI adapter)
    - Schema Agent runnable route (LangServe playground as its own “front”)

---

## 2. State schema (`src/graph/state.py`)

Implement a single `GraphState` (TypedDict with `total=False`) containing at least:

- `messages`: `Annotated[list[AnyMessage], add_messages]` (implementado con `langchain_core.messages.AnyMessage`)
- `mode`: `Literal["schema","query","clarify"]`
- `session_id`: `str`
- `user_preferences`: `dict`

### 2.1 Schema artifacts

- `schema_metadata`: dict (tables/columns/keys)
- `schema_context`: dict (approved context loaded from store)
- `schema_context_draft`: dict (draft to present for HITL)
- `schema_context_answers`: dict (human answers to ambiguity questions)
- `schema_hitl_pending`: bool

### 2.2 Query artifacts

- `query_plan`: dict | str
- `sql_draft`: str
- `sql_validated`: str
- `sql_validation`: dict (issues, needs_human_approval, etc.)
- `query_blocked`: bool (consulta no ejecutable tras validación)
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

Reads the last user message and routes to `"query"` (default).

### 3.2 Schema graph nodes

- `schema_load`
  - loads approved schema context from persistent store
- `schema_inspect_metadata`
  - calls MCP schema inspect tool
- `schema_draft_context`
  - drafts `context_markdown` + ambiguity questions using LLM
  - if questions exist: emits HITL message and ends
- `schema_hitl_resume_loader`
  - parses human answers (JSON) and continues
- `schema_redraft_with_answers`
  - rebuilds context using answers; may re-trigger HITL if still ambiguous
- `schema_persist_context`
  - persists approved context artifact to `DATA_DIR/schema_context.json`

### 3.3 Query flow nodes

- `query_load_context`
  - loads user prefs + approved schema context artifact
  - no schema inspection in query flow (schema-aware context comes from Schema Agent artifact)
- `query_basic_intents`
  - responde preguntas básicas sin SQL (p. ej. "qué podés hacer", "qué tablas hay")
  - usa `schema_metadata` para inventario de tablas y termina el flujo temprano
- `query_planner`
  - Planner step: produces an explicit plan
- `query_sql_executor`
  - Executor step: generates SQL draft
- `query_validator`
  - Critic/validator: safety + correctness checks
  - aplica auto-fix cuando corresponda (p. ej. LIMIT en strict)
  - si queda insegura, bloquea ejecución y pide reformulación en lenguaje natural
- `query_execute`
  - calls MCP read-only SQL execute tool with validated SQL
- `query_explain`
  - crafts final assistant response including:
    - SQL
    - preview/sample rows
    - explanation + limitations
- `query_update_short_term_memory`
  - saves last SQL, filters, assumptions for follow-ups

---

## 4. Edges and routing

### 4.1 Entry point

`START -> router`

### 4.2 Router edges

- router `"query"` -> query flow

### 4.3 Schema edges (high level)

`schema_load -> schema_inspect_metadata -> schema_draft_context`

If `schema_draft_context` emits HITL (questions exist): `END`

Resume path:

`schema_hitl_resume_loader -> schema_inspect_metadata -> schema_redraft_with_answers`

If no more questions: `schema_persist_context -> END`

### 4.4 Query edges (high level)

`query_load_context -> query_planner -> query_sql_executor -> query_validator`

From `query_validator`:

- if blocked: `END` with mensaje de error al usuario
- else: `query_execute`

Then:

`query_execute -> query_explain -> query_update_short_term_memory -> END`

---

## 5. HITL checkpoints (how to implement via chat)

Because UI is OpenAIWeb (generic chat), HITL is done conversationally only for Schema Agent ambiguities:

- Include a machine-readable token for tracking:
  - `HITL_CHECKPOINT_ID=<uuid>`
  - `HITL_KIND=schema_context`

Additionally, for operational UX:

- expose a dedicated Schema Agent front at `/schema-agent/ui` (or equivalent),
- attempt automatic schema-context generation on app startup,
- when Query flow detects missing/stale `schema_context` (schema hash mismatch), auto-regenerate and fall back to Schema HITL UI if ambiguities remain.

The schema flow must parse the next user message:

- `APPROVE` -> proceed
- otherwise treat the user content as edited/answer payload and proceed

---

## 6. Acceptance criteria

- The graph has explicit nodes/edges and a stable state schema.
- Schema flow generates drafts, triggers HITL, and persists approved descriptions.
- Query flow uses planner/executor + validator, triggers HITL for risky queries, executes via MCP tool, returns SQL + sample + explanation.
- Node transitions and tool calls are logged.

