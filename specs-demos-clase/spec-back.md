# Specification: LangGraph ReAct Agent Demo

> **Purpose:** This document is formatted to be fed directly into a coding agent (Cursor/Windsurf/generic LLM coding partner) to generate the implementation of `demo02-langgraph` **from scratch**.

> **Nota:** En el repositorio **TP-multiagentes** el alcance es distinto (dos agentes, MCP, DVD Rental, dos grafos, memoria persistente de schema context, etc.). Para implementación o evaluación del TP usar `spec.md` y `src/specs/`, no este documento como contrato único.

---

## 1. Project Overview

**Goal:** Build an educational demonstration of a **ReAct pattern orchestrated by LangGraph**, exposed **only via an HTTP API**.

**What this demo shows:**
- A LangGraph **StateGraph** implementing a ReAct-style loop: the LLM produces tool calls (Action), the app executes tools (Observation), and the loop continues until the LLM stops calling tools (Final Answer).
- A minimal but complete production-like setup: configuration via pydantic-settings, structured logging, optional LangSmith tracing, and a small test suite.

**Out of scope:**
- No web UI.
- No OpenAI SDK usage directly (all LLM calls are via LangChain `ChatOpenAI`).
- No persistence layer.
- No MCP tools or external tool servers.

---

## 2. Tech Stack

- **Language**: Python `3.13+` (the project pins `>=3.13,<3.14`)
- **Package manager**: `uv` (use `pyproject.toml` + `uv sync`)
- **HTTP API**: `FastAPI` + `LangServe`
- **Agent Orchestration**: `langgraph` (`StateGraph`)
- **LLM Abstraction**: LangChain `langchain-openai.ChatOpenAI` (assumes an OpenAI-compatible endpoint)
- **Observability**: `langsmith` (via LangChain environment variables)
- **Testing**: `pytest` (unit + functional) with `pytest-asyncio` available
- **Lint/format**: `ruff`

---

## 3. Configuration

All configuration must be centralized in `src/config/settings.py` using `pydantic-settings`.

### 3.1 Environment variables (`.env.example`)

Create a root `.env.example` and document these variables:

1. **LLM configuration**
   - `LLM_BASE_URL` (or `LLM_SERVICE_URL`): base URL for the external LLM endpoint (default `http://localhost:8001`)
   - `LLM_API_KEY`: API key for the external LLM service
   - `LLM_MODEL`: model name (default `gpt-4`)

2. **LangSmith tracing**
   - `LANGSMITH_TRACING`: boolean-like flag (default `false`)
   - `LANGSMITH_ENDPOINT`: LangSmith endpoint (default `https://api.smith.langchain.com`)
   - `LANGSMITH_API_KEY`: LangSmith API key
   - `LANGSMITH_PROJECT`: project name (default `langgraph-react-agent`)

3. **Graph execution**
   - `GRAPH_MAX_ITERATIONS`: maximum number of agent-tool cycles (default `10`)

4. **HTTP application**
   - `API_HOST`: FastAPI host (default `0.0.0.0`)
   - `API_PORT`: FastAPI port (default `8000`)
   - `ENVIRONMENT`: application environment name (development/test/production)

### 3.2 Settings module requirements (`src/config/settings.py`)

Implement:
- `LLMSettings` with `env_prefix="LLM_"` and aliases:
  - accept `LLM_BASE_URL` or `LLM_SERVICE_URL` for `base_url`
- `LangSmithSettings` with `env_prefix="LANGSMITH_"`
- `GraphSettings` with `env_prefix="GRAPH_"`
- `ApplicationSettings` with no prefix (explicit variable names `API_HOST`, `API_PORT`, `ENVIRONMENT`)
- A top-level singleton accessor `get_settings()` that caches settings in a module global.

---

## 4. Project Layout (match this structure)

Create the following folder structure:

```
demo02-langgraph/
  pyproject.toml
  uv.lock
  README.md
  Dockerfile
  docker-compose.yml
  .env.example
  spec.md
  src/
    __init__.py
    api/
      __init__.py        # optional, but recommended
      main.py
    agent/
      __init__.py
      graph.py
      edges.py
      nodes.py
      state.py
    tools/
      __init__.py
      base.py
      registry.py
      datetime_tool.py
      python_executor.py
    llm/
      __init__.py
      client.py
    config/
      settings.py
    app_logging/
      __init__.py
      logger.py
      langsmith.py
  tests/
    conftest.py
    unit/
    functional/
```

---

## 5. HTTP API Contract

Implement a FastAPI app in `src/api/main.py` (expose via `get_app()`), and use **LangServe** to expose the agent routes.

### 5.1 CORS

Enable permissive CORS:
- `allow_origins=["*"]`
- allow credentials, methods, and headers as `*`.

### 5.2 Endpoints (LangServe-first)

1. `GET /health`
   - Returns:
     - `{"status": "healthy", "environment": <settings.app.environment>}`

2. LangServe routes mounted at `/react-agent` (using `langserve.add_routes` on the compiled graph runnable).
   - Do **not** hand-write custom FastAPI handlers for agent invocation.
   - Required usable routes:
     - `POST /react-agent/invoke`
     - `POST /react-agent/stream` (if streaming is enabled for the runnable)
     - `GET /react-agent/playground` (LangServe playground UI)
   - Behavior:
     - Input payload is LangServe runnable input (graph state input or adapter input).
     - Output is produced by the compiled LangGraph runnable.

3. Optional compatibility route (only if needed by a consuming client):
   - `POST /v1/chat/completions` may exist as a thin adapter, but this is **not required** by default.
   - If implemented, it must delegate internally to the same compiled LangGraph runnable.

### 5.3 Graph execution helper (for wiring and tests)

Implement a helper `_run_graph_for_query(query: str) -> str` that:
- gets the compiled graph
- creates initial state from `HumanMessage(content=query)` and `settings.graph.max_iterations`
- invokes the graph
- returns the content of the last message in the returned `messages` list

Use this helper for internal testing or optional adapters, but prefer direct LangServe route wiring for public agent endpoints.

---

## 6. LangGraph Agent Design

### 6.1 State schema (`src/agent/state.py`)

Define `AgentState` as a `TypedDict(total=False)` including:
- `messages`: `Annotated[list[AnyMessage], add_messages]`
- `iteration`: `int`
- `max_iterations`: `int`

Define:
- `initial_state(messages: list[AnyMessage], max_iterations: int) -> AgentState`
  - sets `iteration=0`
  - sets `messages=messages`
  - sets `max_iterations=max_iterations`

### 6.2 Routing logic (`src/agent/edges.py`)

Implement `route_after_agent(state: AgentState) -> Literal["tools","end"]`:
- If there are tool calls on the last message and `iteration < max_iterations`:
  - return `"tools"`
- Otherwise:
  - return `"end"`

Tool calls are detected via `getattr(last_message, "tool_calls", None) or []`.

### 6.3 Agent nodes (`src/agent/nodes.py`)

Implement two LangGraph nodes:

1. `agent_node(state: AgentState) -> AgentState`
   - Create a tool registry (singleton) pre-populated with:
     - `PythonExecutorTool`
     - `DateTimeTool`
   - Convert these tools into LangChain tools with `args_schema` when provided:
     - Use `LangChainTool.from_function(...)`
     - Tool callable should dispatch to `ToolRegistry.execute_tool(tool.name, **kwargs)`
   - Ensure the message list starts with a `SystemMessage`:
     - If the first message is already a `SystemMessage`, keep it.
     - Otherwise prepend a `SystemMessage` instructing the model it may call:
       - Python code execution
       - current date/time
     - Include `environment` in `additional_kwargs` using `settings.app.environment`.
   - Bind tools to the LLM (`LLMClient.bind_tools(tools)`).
   - Invoke the model with the (possibly prepended) messages.
   - Append the model response to `messages`.
   - Increment `iteration` by 1.

2. `tools_node(state: AgentState) -> AgentState`
   - Read the last message and extract `tool_calls`.
   - For each tool call:
     - Support both dict-like and object-like forms:
       - name: `call.name` or `call["name"]`
       - args: `call.args` or `call["args"]`
       - id: `call.id` or `call["id"]`
     - Execute via `registry.execute_tool(name, **args)`
     - Append a `ToolMessage(content=<result>, tool_call_id=<id-or-empty>)`
   - Return updated state with appended tool messages.

### 6.4 Graph builder (`src/agent/graph.py`)

Implement:
- `build_graph() -> StateGraph`:
  - `graph = StateGraph(AgentState)`
  - add nodes: `"agent"`, `"tools"`
  - set entry point to `"agent"`
  - add conditional edges from `"agent"` using `route_after_agent`:
    - `"tools" -> "tools"`
    - `"end" -> END`
  - add edge `"tools" -> "agent"`
- `get_compiled_graph()`:
  - compile the graph with `interrupt_before=[]`

### 6.5 Iteration limits

The loop must stop when:
- the LLM produces no tool calls (end), or
- `state["iteration"]` reaches `state["max_iterations"]` (end).

---

## 7. Tools

### 7.1 Base interface (`src/tools/base.py`)

Create an abstract `BaseTool(ABC)`:
- class attributes:
  - `name: str`
  - `description: str`
  - `parameters: dict` describing tool arguments (including required/optional and description)
  - `args_schema: type[pydantic.BaseModel] | None` for LangChain tool arg schema
- abstract method:
  - `execute(self, **kwargs: object) -> str`
- implement:
  - `validate_parameters(self, **kwargs: object) -> bool`
    - return `False` when a required param is missing

### 7.2 Tool registry (`src/tools/registry.py`)

Implement `ToolRegistry` with:
- register tool: `register(tool: BaseTool) -> None`
- list tools: `list_tools() -> list[BaseTool]`
- dispatch execute: `execute_tool(name: str, **kwargs) -> str`
  - raise `ValueError` when tool not found or validation fails

### 7.3 DateTime tool (`src/tools/datetime_tool.py`)

Implement:
- `DateTimeInput(BaseModel)` with optional `timezone: str | None`
- `DateTimeTool(BaseTool)`:
  - `name = "datetime"`
  - `args_schema = DateTimeInput`
  - `parameters` includes `timezone` as optional
  - `execute(timezone: str | None = None) -> str`
    - use `datetime.now(ZoneInfo(timezone))` if timezone provided
    - otherwise `datetime.now()`
    - return formatted string `"%Y-%m-%d %H:%M:%S %Z"`
    - on errors: return `"Error getting date/time: <exc>"`

### 7.4 Python executor tool (`src/tools/python_executor.py`)

Implement:
- `PythonExecutorInput(BaseModel)` with `code: str`
- `PythonExecutorTool(BaseTool)`:
  - `name = "python_executor"`
  - `args_schema = PythonExecutorInput`
  - `parameters` includes required `code`
  - `execute(code: str) -> str`:
    - capture stdout using `contextlib.redirect_stdout`
    - execute code in isolated namespace using `exec(code, namespace)`
    - if stdout is empty, try `eval(code, namespace)` as a fallback
    - return:
      - stdout if any
      - otherwise result of eval if any
      - otherwise `"Code executed successfully (no output)"`
    - on errors:
      - `SyntaxError` => `"Syntax error: <exc>"`
      - other exceptions => `"Error: <exc>"`

---

## 8. LLM Client (`src/llm/client.py`)

Implement `LLMClient`:
- Internally use `langchain_openai.ChatOpenAI`
- Construct it with:
  - `base_url=settings.llm.base_url`
  - `api_key=settings.llm.api_key` (or fallback to `"dummy-key"` if empty)
  - `model=settings.llm.model`
  - `temperature=0.0`
- Provide:
  - `generate(prompt: str, **kwargs) -> str`:
    - call `self._llm.invoke(prompt, **kwargs)` and return `.content`
  - `bind_tools(tools: Sequence[object]) -> BaseChatModel`:
    - return `self._llm.bind_tools(tools)`

---

## 9. Logging + LangSmith (`src/app_logging/*`)

### 9.1 Logging

Implement `configure_logging()` in `src/app_logging/logger.py`:
- Determine log level from `settings.app.environment.upper()`:
  - if attribute exists in `logging` module, use it
  - otherwise fallback to `logging.INFO`
- Configure `logging.basicConfig(level=..., format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")`

### 9.2 LangSmith tracing

Implement `configure_langsmith()` in `src/app_logging/langsmith.py`:
- If `settings.langsmith.tracing` is true and `settings.langsmith.api_key` is non-empty:
  - set env vars:
    - `LANGCHAIN_TRACING_V2="true"`
    - `LANGCHAIN_ENDPOINT=settings.langsmith.endpoint`
    - `LANGCHAIN_API_KEY=settings.langsmith.api_key`
    - `LANGCHAIN_PROJECT=settings.langsmith.project`
- Else set `LANGCHAIN_TRACING_V2="false"`

Also suppress LangSmith warnings when the API key is missing.

---

## 10. Docker Support

### 10.1 Dockerfile

Create `Dockerfile` that:
- uses `python:3.13-slim`
- installs `uv` via `pip`
- `uv sync --frozen --no-dev` using `pyproject.toml`
- copies `src` into `/app/src`
- sets `PYTHONPATH=/app/src`
- exposes port `8000`
- healthcheck uses `curl -f http://localhost:8000/health`
- runs:
  - `uv run uvicorn api.main:get_app --host 0.0.0.0 --port 8000`

### 10.2 docker-compose

Create `docker-compose.yml` that defines service `react-agent`:
- builds from `.` using `Dockerfile`
- maps `8002:8000`
- loads environment via `.env`
- mounts `./src:/app/src` for development
- sets environment:
  - `API_HOST=0.0.0.0`
  - `API_PORT=8000`
  - `ENVIRONMENT=development`
  - `GRAPH_MAX_ITERATIONS=10` (and optionally other graph envs)
- includes a healthcheck calling `GET /health`

---

## 11. Testing Requirements (pytest)

### 11.1 Testing style

All tests must be plain pytest functions (no classes) and follow:
- Given / When / Then / Clean pattern (as used in other demos in this repository).

### 11.2 Test fixtures

Implement `tests/conftest.py` to load `.env` from the project root before any app code import:
- use `python-dotenv` `load_dotenv()`
- assert it loads successfully (so functional tests can configure real LLM + LangSmith if needed)

### 11.3 Functional tests to implement

Write functional tests using FastAPI `TestClient`:
- `GET /health` returns status `"healthy"`
- `POST /react-agent/invoke` returns a successful LangServe runnable response
- `GET /react-agent/playground` is reachable
- `/react-agent/invoke` can use:
  - `datetime` tool when asked for current date/time
  - `python_executor` tool for a known computation (e.g. expecting `56088` for `123*456`)
- If `/v1/chat/completions` adapter is implemented, add optional tests for it; otherwise do not require those tests.

### 11.4 Unit tests to implement

Write unit tests covering:
- `AgentState.initial_state(...)` sets iteration to `0` and stores messages/max_iterations
- `ToolRegistry`:
  - register and list tools
  - execute dispatches correctly
  - raises `ValueError` for missing tools
- `BaseTool.validate_parameters` enforces required fields
- `DateTimeTool.execute`:
  - returns a timestamp-like string without timezone
  - returns an `"Error ..."` message on invalid timezone
- `PythonExecutorTool.execute`:
  - captures stdout
  - returns a syntax error message on invalid code
- Agent routing logic:
  - routes to `"tools"` when tool_calls are present
  - routes to `"end"` when no tool_calls are present
  - respects `max_iterations`
- Graph wiring:
  - `build_graph` contains nodes `"agent"` and `"tools"`
  - `get_compiled_graph` can run with a patched `agent_node`
- Node behavior:
  - `agent_node` appends the AI response and increments iteration
  - `tools_node` executes tool_calls and appends `ToolMessage` results

---

## 12. Acceptance Criteria

The project is complete when:
- Running the app exposes:
  - `GET /health`
  - LangServe routes under `/react-agent` (at least `/invoke` and `/playground`)
- A user query can trigger the tool loop:
  - If tool calls are requested by the model, `tools_node` executes them and appends tool observations.
  - If no tool calls are requested, the graph ends and returns a final assistant answer.
- The tool registry contains exactly:
  - `python_executor`
  - `datetime`
- `pytest` passes (unit + functional).
- `ruff` passes (formatting + lint), using:
  - `uv run ruff check --fix && uv run ruff format`

---

## 13. Implementation Checklist for the Coding Agent

1. Create the `demo02-langgraph` folder structure (Section 4).
2. Implement `pyproject.toml` (dependencies as per Section 2).
3. Implement `src/config/settings.py` and `.env.example`.
4. Implement logging + LangSmith setup (`src/app_logging/*`) and ensure `api/main.py` calls them at import time.
5. Implement the LLM client (`src/llm/client.py`) and tool registry + tools (`src/tools/*`).
6. Implement LangGraph:
   - `src/agent/state.py`
   - `src/agent/edges.py`
   - `src/agent/nodes.py`
   - `src/agent/graph.py`
7. Implement API exposure in `src/api/main.py` using LangServe `add_routes(...)` exactly as in Section 5 (no manual agent endpoint handlers).
8. Implement Dockerfile + docker-compose (Section 10).
9. Implement tests (Section 11) and run `uv run python -m pytest`.
10. Fix lint/format with `uv run ruff check --fix && uv run ruff format`.

---

## 14. Prompt for the Coding Agent

> You are an expert Python developer specialized in AI Agents.
>
> Implement the `demo02-langgraph` project **exactly as described in this specification**.
>
> Requirements:
> 1. Use `uv` + `pyproject.toml`. No `requirements.txt`.
> 2. Use LangGraph `StateGraph` with nodes `agent` and `tools`, routed by `route_after_agent`.
> 3. Use LangChain `ChatOpenAI` for the model (OpenAI-compatible external endpoint). Do not implement the LLM service.
> 4. Implement exactly two tools in the tool registry:
>    - `python_executor`
>    - `datetime`
> 5. Implement endpoint exposure with LangServe under `/react-agent` (plus `/health` in FastAPI). Do not manually implement agent invocation handlers.
> 6. Keep tests as plain pytest functions following Given/When/Then/Clean.
> 7. Add Docker support (Dockerfile + docker-compose) matching the spec.
>
> Start by creating the file structure, then implement the configuration + tools, then the LangGraph nodes/edges/graph, then the API, then tests.

