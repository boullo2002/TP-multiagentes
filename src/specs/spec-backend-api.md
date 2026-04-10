# Specification — Backend API (FastAPI + LangServe + OpenAI-compatible)

> **Purpose:** Define the backend HTTP contract and service wiring for the TP, using the same technologies/patterns as the class demos: FastAPI + LangServe + env-driven config.

---

## 1. Purpose and scope

- **Purpose**: Expose the LangGraph multi-agent system through:
  - LangServe routes (debug/playground/testing)
  - an OpenAI-compatible adapter endpoint (required for OpenAIWeb)
- **Scope**:
  - One FastAPI service `app` (dockerized)
  - Uses LangServe `add_routes(...)`
  - Also exposes `POST /v1/chat/completions` as a thin adapter
  - Includes `/health` and permissive CORS

Out of scope:

- Authentication / multi-user accounts
- Long-term chat history persistence (not required)

---

## 2. Tech stack

- **FastAPI**
- **LangServe**
- **pydantic-settings**
- **uv** (pyproject)

---

## 3. Configuration

All settings live in `src/config/settings.py`. Minimum vars:

- `API_HOST`, `API_PORT`, `ENVIRONMENT`
- `GRAPH_MAX_ITERATIONS`
- `LLM_BASE_URL` (or `LLM_SERVICE_URL` alias), `LLM_API_KEY`, `LLM_MODEL`, `LLM_REQUEST_TIMEOUT` (seconds per LLM HTTP call)
- `MCP_SERVER_URL`, `MCP_REQUEST_TIMEOUT_MS`
- `DATA_DIR`
- `DEFAULT_LIMIT`, `SQL_SAFETY_STRICTNESS`

---

## 4. FastAPI app requirements (`src/api/main.py`)

### 4.1 App factory

Implement `get_app()` that:

- loads settings
- configures logging + optional LangSmith (at import or app creation time)
- sets up CORS
- mounts LangServe routes
- registers `/health` + OpenAI adapter routes

### 4.2 CORS

Enable permissive CORS:

- allow origins: `*`
- allow methods/headers/credentials: `*`

### 4.3 Endpoint: `GET /health`

Return:

```json
{ "status": "healthy", "environment": "development" }
```

### 4.4 LangServe routes

Mount the compiled runnable at `/tp-agent`:

- `POST /tp-agent/invoke`
- `GET /tp-agent/playground`

**Rule:** Do not hand-write custom “invoke agent” handlers. Use `langserve.add_routes`.

### 4.5 OpenAI-compatible adapter

Implement:

`POST /v1/chat/completions`

Behavior:

- Accept `model`, `messages`, optional `stream`.
- If `stream=false` (default), return a normal JSON `chat.completion`.
- If `stream=true`, return **`text/event-stream`** SSE in OpenAI format (`chat.completion.chunk` events, ending with `data: [DONE]`). The graph still runs to completion first; tokens are streamed **after** the runnable finishes (UI shows progress while the graph runs only indirectly once chunks start).
- Convert input messages into the runnable input shape expected by the LangGraph compiled runnable.
- Invoke the same runnable used by LangServe.
- Return an OpenAI-compatible response including:
  - `id`, `object`, `created`, `model`
  - `choices: [{index, message: {role, content}, finish_reason}]`

Minimum response example:

```json
{
  "id": "chatcmpl-tp-001",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "tp-multiagentes",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "..." },
      "finish_reason": "stop"
    }
  ]
}
```

Also implement **`GET /v1/models`** (OpenAI-compatible list). Clients such as Open WebUI call this to populate the model dropdown; return at least one model entry (e.g. id from `LLM_MODEL`).

### 4.6 Error handling

- Connection failures to MCP server must yield a clear 503-like error.
- SQL execution errors must be returned as safe user-readable messages (and logged).
- Validation failures (unsafe SQL) must return a normal assistant message explaining why it was blocked and what clarification is needed.

---

## 5. Acceptance criteria

1. `GET /health` returns healthy JSON.
2. `GET /tp-agent/playground` is reachable.
3. `POST /tp-agent/invoke` works and triggers graph execution.
4. `POST /v1/chat/completions` works with OpenAIWeb and returns OpenAI-compatible JSON.
5. `GET /v1/models` returns a valid OpenAI-compatible model list for the UI.
6. CORS is permissive and OpenAIWeb can call the API.

