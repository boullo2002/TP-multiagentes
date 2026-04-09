# Specification — LangGraph Workflow (Two-Agent System)

> **Purpose:** Define the LangGraph StateGraph orchestration for the TP: explicit state, nodes, edges, routing, HITL checkpoints, and validator step.

---

## 1. Purpose and scope

- **Purpose**: Implement a **two-agent** multi-agent workflow in LangGraph:
  - Schema Agent flow for schema documentation + approvals
  - Query Agent flow for NL→SQL + validation + safe execution + explanation
- **Scope**:
  - Single compiled graph used by both:
    - LangServe runnable routes
    - OpenAI-compatible adapter (`/v1/chat/completions`)

---

## 2. State schema (`src/graph/state.py`)

Implement a single `GraphState` (TypedDict with `total=False`) containing at least:

- `messages`: `Annotated[list[AnyMessage], add_messages]`
- `mode`: `Literal["schema","query","clarify"]`
- `session_id`: `str`
- `user_preferences`: `dict`

### 2.1 Schema artifacts

- `schema_metadata`: dict (tables/columns/keys)
- `schema_descriptions`: dict (approved descriptions loaded from store)
- `schema_descriptions_draft`: dict (draft to present for HITL)
- `schema_hitl_pending`: bool

### 2.2 Query artifacts

- `query_plan`: dict | str
- `sql_draft`: str
- `sql_validated`: str
- `sql_validation`: dict (issues, needs_human_approval, etc.)
- `query_hitl_pending`: bool
- `query_result`: dict (columns, rows, row_count, execution_ms)
- `last_error`: str | None

### 2.3 Short-term memory snapshot

- `short_term`: dict (last_sql, last_filters, recent_tables, open_assumptions, etc.)

---

## 3. Nodes (required)

Implement the graph in `src/graph/workflow.py` with explicit nodes:

### 3.1 `router`

Reads the last user message and routes to:

- `"schema"` if user asks to document/explain schema, tables, columns, relationships
- `"query"` if user asks a data question
- `"clarify"` if ambiguous (ask a clarification question)

### 3.2 Schema flow nodes

- `schema_load_existing_descriptions`
  - loads approved descriptions from persistent store
- `schema_inspect_metadata`
  - calls MCP schema inspect tool
- `schema_draft_descriptions`
  - drafts table + column descriptions using LLM
  - sets `schema_hitl_pending = true`
- `schema_hitl_review`
  - HITL checkpoint node: waits for user approval/edits (via chat)
  - if approved: `schema_hitl_pending=false` and proceed
  - if edited: update draft and proceed
- `schema_persist_descriptions`
  - persists approved descriptions

### 3.3 Query flow nodes

- `query_load_context`
  - loads user prefs + approved schema descriptions
  - may call MCP schema tool for targeted metadata if needed
- `query_planner`
  - Planner step: produces an explicit plan
- `query_sql_executor`
  - Executor step: generates SQL draft
- `query_validator`
  - Critic/validator: safety + correctness checks
  - if `needs_human_approval`: set `query_hitl_pending=true`
- `query_hitl_review`
  - HITL checkpoint for risky queries; user can approve or request changes
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

- router `"schema"` -> schema flow
- router `"query"` -> query flow
- router `"clarify"` -> node that asks the user a short question and then ends

### 4.3 Schema edges (high level)

`schema_load_existing_descriptions -> schema_inspect_metadata -> schema_draft_descriptions -> schema_hitl_review`

From `schema_hitl_review`:

- if pending (no approval yet): remain in hitl (or end with a “please reply with approval/edits” message)
- if approved: `schema_persist_descriptions -> END`

### 4.4 Query edges (high level)

`query_load_context -> query_planner -> query_sql_executor -> query_validator`

From `query_validator`:

- if needs HITL: `query_hitl_review`
- else: `query_execute`

Then:

`query_execute -> query_explain -> query_update_short_term_memory -> END`

---

## 5. HITL checkpoints (how to implement via chat)

Because UI is OpenAIWeb (generic chat), HITL is done conversationally:

- The system must emit a clear instruction message:
  - “Reply with **APPROVE** to accept, or paste the corrected version.”
- Include a machine-readable token for tracking:
  - `HITL_CHECKPOINT_ID=<uuid>`
  - `HITL_KIND=schema_descriptions` or `HITL_KIND=sql_execution`

The graph must parse the next user message:

- `APPROVE` -> proceed
- otherwise treat the user content as edited draft and proceed (with minimal validation)

---

## 6. Acceptance criteria

- The graph has explicit nodes/edges and a stable state schema.
- Schema flow generates drafts, triggers HITL, and persists approved descriptions.
- Query flow uses planner/executor + validator, triggers HITL for risky queries, executes via MCP tool, returns SQL + sample + explanation.
- Node transitions and tool calls are logged.

