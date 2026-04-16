# TP Multiagentes — NLQ sobre DVD Rental (LangGraph + MCP) — Specification

> **Purpose:** This document is formatted to be fed directly into a coding agent (Cursor/Windsurf/generic LLM coding partner) to generate the implementation of this TP **from scratch**, following the **same style and technologies** used in the class demos.
>
> **Mandatory dataset:** PostgreSQL **DVD Rental** sample database (baseline for development, evaluation, and demo).
>
> **Mandatory architecture:** **LangGraph** workflow + **exactly two specialized agents** + **persistent + short-term memory** + **MCP tools** + **HITL** + **critic/validator** + **observability**.

---

## 1. Project Overview

### 1.1 Goal

Build a production-style prototype of a **Natural Language Query (NLQ) System** over a PostgreSQL database (DVD Rental), implemented as a **two-agent LangGraph system**:

1) **Schema Documentation Flow (with Human-in-the-Loop)**
- Inspect the DB schema (tables, columns, types, PK/FK, constraints).
- Build an **approved schema context artifact** for NL→SQL consumption.
- Ask for **human confirmation/edits** when ambiguous.
- Persist **approved** schema context.

2) **Natural Language Query → SQL Flow**
- Interpret user questions.
- Generate safe SQL using metadata + approved schema context artifact.
- Execute SQL in **read-only** mode.
- Return:
  - the SQL produced,
  - a preview/sample of result rows,
  - a concise explanation and limitations,
  - support follow-up refinement using short-term memory.

### 1.2 What this TP demonstrates (must be visible in code + docs)

- **LangGraph StateGraph** orchestration with explicit nodes, edges, routing, and state.
- **Two-agent decomposition**:
  - Schema Agent
  - Query Agent
- **Agent patterns**:
  - Planner/Executor (or equivalent explicit decomposition)
  - HITL checkpoints (schema approvals + risky query execution approvals)
  - Critic/Validator step before final SQL execution
- **Memory**:
  - Persistent user preferences across sessions
  - Short-term conversation/session context
- **MCP integration**:
  - schema inspection tool
  - read-only SQL execution tool
- **Observability**:
  - node transitions
  - tool calls
  - HITL interactions
  - retries/fallback behavior

---

## 2. Tech Stack (match class demos)

- **Language**: Python `3.13+` (pin `>=3.13,<3.14`)
- **Package manager**: `uv` (`pyproject.toml` + `uv sync`)
- **HTTP API**: `FastAPI` + `LangServe`
- **Agent orchestration**: `langgraph` (`StateGraph`)
- **LLM**: `langchain-openai.ChatOpenAI` (OpenAI-compatible base URL)
- **Config**: `pydantic-settings`
- **Observability**: standard logging + optional LangSmith
- **Testing**: `pytest` (+ `pytest-asyncio` if needed)
- **Lint/format**: `ruff`
- **Containers**: Docker + Docker Compose
- **UI**: **OpenAIWeb** (dockerized) configured to call the OpenAI-compatible endpoint

---

## 3. Repository layout (match this structure)

Create this structure in the repo root:

```
TP-multiagentes/
  spec.md
  README.md
  REPORT.md
  pyproject.toml
  uv.lock
  Dockerfile
  docker-compose.yml
  .env.example
  docker/
    db/
      init/
        01_restore_dvdrental.sh
  db-data/
    dvdrental.zip                # dataset zip committed/provided in repo
  src/
    __init__.py
    api/
      __init__.py
      main.py
    graph/
      __init__.py
      workflow.py                  # compat wrapper (Query graph)
      query_workflow.py
      schema_workflow.py
      state.py
      edges.py
      checkpoints.py
    agents/
      __init__.py
      schema_agent.py
      query_agent.py
      prompts.py
      planner.py
      validator.py
    tools/
      __init__.py
      mcp_client.py
      mcp_schema_tool.py
      mcp_sql_tool.py
      sql_safety.py
    memory/
      __init__.py
      persistent_store.py
      session_store.py
      schema_context_store.py
    app_logging/
      __init__.py
      logger.py
      langsmith.py
    config/
      settings.py
    contracts/
      __init__.py
      openai_compat.py
  mcp_server/
    __init__.py
    server.py
    tools/
      __init__.py
      schema.py
      sql.py
  ui/
    README.md
    Dockerfile
    # OpenAIWeb config/assets as required by the version used in class
  tests/
    conftest.py
    unit/
    functional/
```

If you change any paths, document the mapping in `README.md`.

---

## 4. Configuration (`.env.example` + pydantic-settings)

All configuration must be centralized in `src/config/settings.py` using `pydantic-settings`, following the demo style.

### 4.1 Environment variables

Create root `.env.example` including at least:

#### LLM
- `LLM_BASE_URL` (alias: accept `LLM_SERVICE_URL`) — base URL of OpenAI-compatible endpoint
- `LLM_API_KEY`
- `LLM_MODEL` (default: `gpt-4`)

#### LangSmith (optional)
- `LANGSMITH_TRACING` (default: `false`)
- `LANGSMITH_ENDPOINT` (default: `https://api.smith.langchain.com`)
- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT` (default: `tp-multiagentes`)

#### Graph
- `GRAPH_MAX_ITERATIONS` (default: `12`)

#### App
- `API_HOST` (default: `0.0.0.0`)
- `API_PORT` (default: `8000`)
- `ENVIRONMENT` (development/test/production)

#### Database
- `DATABASE_URL` (for app-internal DB access, only if needed)

#### MCP
- `MCP_SERVER_URL` (e.g. `http://mcp:7000`)
- `MCP_REQUEST_TIMEOUT_MS` (default: `120000`)

#### Memory / Storage
- `DATA_DIR` (default: `/app/data` in containers)

#### Safety
- `DEFAULT_LIMIT` (default: `50`)
- `SQL_SAFETY_STRICTNESS` (default: `strict`)

---

## 5. HTTP API Contract (FastAPI + LangServe + OpenAI adapter)

Implement FastAPI in `src/api/main.py` exporting `get_app()`.

### 5.1 CORS

Enable permissive CORS:
- `allow_origins=["*"]`
- allow credentials/methods/headers as `*`

### 5.2 Endpoints

1) `GET /health`
- Returns:
  - `{"status": "healthy", "environment": "<ENVIRONMENT>"}`

2) LangServe routes mounted at `/tp-agent`
- Use `langserve.add_routes(app, runnable, path="/tp-agent")`
- Required routes:
  - `POST /tp-agent/invoke`
  - `GET /tp-agent/playground`

3) OpenAI-compatible adapter route (required for OpenAIWeb)

`POST /v1/chat/completions`

- **Request body**: OpenAI-compatible minimal:
  - `model: str`
  - `messages: [{role, content}]`
  - `stream: bool` — if `false`, JSON `chat.completion`; if `true`, SSE `text/event-stream` (`chat.completion.chunk` + `data: [DONE]`)

- **Response body** (non-streaming): OpenAI-compatible minimal:
  - `choices[0].message.content: str`

**Rule:** This endpoint must delegate to the same compiled LangGraph runnable used by LangServe routes.

4) Schema Agent front (LangServe playground)

- `GET /schema-agent/playground`
- Optional convenience endpoint: `GET /schema` → returns the playground path

---

## 6. LangGraph design (two-agent workflow)

The system must expose **two independent graphs**:

- **Schema graph** (Schema Agent): inspect → draft context → HITL (if ambiguous) → persist `schema_context.json`
- **Query graph** (Query Agent): load context (approved `schema_context.json` + prefs) → planner → executor → validator → execute → explain + memory

Query Agent must read the schema context from the file produced by Schema Agent (no embedded schema flow in the query graph).
  - planner
  - executor (SQL draft)
  - critic/validator
  - HITL approval for risky queries
  - execute via MCP
  - explain results + update short-term memory

See detailed specs in:

- `src/specs/spec-backend-api.md`
- `src/specs/spec-langgraph-workflow.md`
- `src/specs/spec-agents.md`
- `src/specs/spec-mcp.md`
- `src/specs/spec-memory.md`
- `src/specs/spec-ui-openaiweb.md`
- `src/specs/spec-docker.md`
- `src/specs/spec-tests.md`

---

## 7. Deliverables

- Working codebase in this repo.
- `README.md` including:
  - architecture diagram of the graph
  - setup/run instructions (docker-first)
  - memory design (persistent vs short-term)
  - MCP tools used and role
  - agent patterns used
- `REPORT.md` (1–2 pages) trade-offs and design choices.
- Demo script in README (or `scripts/demo.md`).

---

## 8. Acceptance criteria (project-level)

The submission is complete only if:

- Built with LangGraph StateGraph and explicit routing/state.
- Exactly two specialized agents are implemented and used.
- HITL exists for schema documentation approvals.
- Persistent preferences exist across sessions.
- Short-term memory exists for follow-up continuity.
- MCP tools exist and are invoked from graph nodes.
- SQL execution is safe and read-only only.
- Results include SQL + sample rows + explanation.
- All demos use DVD Rental dataset.
- `ruff` + `pytest` pass.

---

## 9. Prompt for the coding agent (implementation)

> Implement this TP exactly as described in `spec.md` and all specs under `src/specs/`.
>
> Requirements:
> - Use `uv` + `pyproject.toml` (no requirements.txt).
> - Use FastAPI + LangServe.
> - Use LangGraph StateGraph with explicit nodes/edges/routing/state.
> - Implement exactly two specialized agents (Schema + Query).
> - Implement persistent + short-term memory.
> - Implement MCP server as a separate service in docker-compose and call it from the graph.
> - Expose OpenAI-compatible `/v1/chat/completions` adapter for OpenAIWeb UI.
> - Enforce read-only SQL safety with a critic/validator and HITL for risky queries.
> - Add logging for node transitions, tool calls, and HITL events.
> - Add pytest unit + functional tests and ruff lint/format.

