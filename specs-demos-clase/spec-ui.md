# Streamlit Chat Bot — Specification

A Streamlit web app that acts as a chat client for the LangGraph ReAct Agent HTTP API. Users converse with the agent through a chat interface; all messages are sent to and responses received from the API (no web UI or playground on the API side).

**Nota (TP-multiagentes):** el chat principal del usuario final va con **Open WebUI** contra `POST /v1/chat/completions` (Query Agent). **Streamlit** en ese repo es el servicio `schema-ui` (`schema_agent_front/app.py`) y opera el Schema Agent vía `SCHEMA_AGENT_BACKEND_URL`, no sustituye al patrón de este spec genérico salvo como analogía de “UI en contenedor”.

---

## 1. Purpose and scope

- **Purpose**: Provide a simple web UI to chat with the ReAct agent via its HTTP API.
- **Scope**: One Streamlit app that:
  - Maintains chat history (session-only).
  - Sends user messages to the API and displays assistant replies.
  - Supports optional streaming of responses.
  - Handles API errors and connection issues gracefully.

Out of scope: authentication, persistence of history across sessions, or direct tool invocation (tools are used internally by the agent).

---

## 2. Tech stack

- **UI**: Streamlit.
- **HTTP client**: `httpx` (supports sync and async, and streaming responses) or `requests` (simpler, no streaming in a single read). Prefer `httpx` if streaming is required.
- **Config**: Environment variables and/or `.env` (e.g. via `python-dotenv`).
- **Python**: 3.11+ recommended, consistent with the API service.

---

## 3. Configuration

### 3.1 Environment variables

All configuration is read from environment variables. **When running in a container, the API URL must be set via env** (e.g. in Docker Compose or Kubernetes); there is no in-app UI to change the API base URL in that deployment.

| Variable     | Required (container) | Default              | Description                    |
| ------------ | -------------------- | -------------------- | ------------------------------ |
| `API_BASE_URL` | **yes**            | `http://localhost:8000` (local only) | Base URL of the LangGraph API. **Must be set in container.** |
| `API_TIMEOUT`  | no                 | `120` (seconds)      | Timeout for non-streaming requests |
| `STREAM_DEFAULT` | no               | `true`               | Use streaming by default in the UI |

The app must run with the API reachable at `API_BASE_URL`. In containerized runs, the host/port will differ from localhost (e.g. `http://langgraph:8000` or the external API URL).

### 3.2 Container deployment

The app **runs in a container** (Docker). The container image runs the Streamlit app and expects:

- **`API_BASE_URL`** to be set in the container environment (e.g. via `docker run -e API_BASE_URL=...` or in `docker-compose` `environment`). This is the URL the app uses for all API calls; no config file or UI override is required or expected in production.
- Optional: `API_TIMEOUT`, `STREAM_DEFAULT`, `CHAT_MODEL` as above.

Local development may use `.env` or defaults; in the container, at least `API_BASE_URL` must be provided.

---

## 4. API usage

The app **must** use the following endpoints as documented in the API Usage document.

### 4.1 Health check (optional but recommended)

- **Endpoint**: `GET {API_BASE_URL}/health`
- **When**: On app load or via a “Check API” button; optional periodic check.
- **Use**: Display connection status (e.g. “API connected” / “API unavailable”) and optionally disable send or show a warning if unhealthy.

### 4.2 Chat

Use the **OpenAI-compatible chat completions** endpoint for the chat experience (so the UI can support multiple messages and, if desired, streaming).

- **Endpoint**: `POST {API_BASE_URL}/v1/chat/completions`
- **Request body**:
  - `model`: string (required). Use a fixed value, e.g. `"gpt-4"` or a configurable `CHAT_MODEL` (default `"gpt-4"`).
  - `messages`: array of `{ "role": "user" | "assistant" | "system", "content": string }`. For a simple implementation, the spec may require only the **current user message** (see API note). For a richer UX, send full conversation history so the API can use it if/when the backend supports it.
  - `stream`: boolean. If `true`, the app must consume the SSE stream and display tokens as they arrive.

**Note (from API doc):** The agent currently uses only the **last user message**. Sending the full `messages` array is still recommended for future compatibility and a consistent client contract.

### 4.3 Alternative: simple ReAct endpoint

- **Endpoint**: `POST {API_BASE_URL}/react-agent`
- **Request body**: `{ "query": "<user message>" }`
- **Use**: Optional alternative for a “single query” mode (no conversation history). Not required for the main chat UX but may be mentioned in the spec as an alternative.

The **primary** integration for the Streamlit bot must be **`/v1/chat/completions`** (with optional streaming).

---

## 5. Features

### 5.1 Chat UI

- **Message history**: Session-scoped list of messages (user + assistant). No persistence to disk or DB required.
- **Input**: Text area or chat input for the user message; “Send” (and optionally Enter to send).
- **Display**: Each message shown with role (user vs assistant), in chronological order. Assistant messages may be rendered as markdown if Streamlit supports it.
- **Streaming**: If streaming is enabled:
  - Show a single assistant message placeholder that updates incrementally as SSE events arrive.
  - Handle `data: [DONE]` as end of stream.
- **Non-streaming**: If streaming is off, show the full assistant message when the request completes.

### 5.2 Configuration in UI (optional)

- **Streaming toggle**: Checkbox or switch to enable/disable streaming (default from `STREAM_DEFAULT`).
- **API base URL**: Not configurable in the UI when running in a container; the app uses `API_BASE_URL` from the environment only. For local dev, an optional override in the sidebar may be supported.

### 5.3 Error handling

- **Connection errors**: Show clear message (e.g. “Cannot reach API at …”) and suggest checking URL and that the API is running.
- **4xx/5xx**: Display API error body (e.g. `detail`) in the UI; do not crash the app.
- **Timeout**: On timeout, show a message and allow the user to retry.
- **Empty input**: Do not send request; optionally show a short validation message.

### 5.4 CORS

CORS is already enabled on the API (`allow_origins=["*"]`). The Streamlit app will run on its own origin (e.g. `localhost:8501`); no extra CORS configuration is required in the spec unless the app is served from a different domain in production.

---

## 6. UI/UX guidelines

- **Layout**: Simple: title/header, chat history area, input at the bottom (or sidebar for settings).
- **Accessibility**: Use clear labels and avoid relying only on color for status.
- **Performance**: For streaming, update the UI incrementally without blocking the main thread (Streamlit’s behavior for streaming components should be documented or tested).
- **Empty state**: On first load, show a short instruction (e.g. “Type a message and send to chat with the ReAct agent.”).

---

## 7. Project structure (suggested)

```
demo02-ui/
  spec.md                 # This specification
  README.md               # How to run the app (local + container) and env vars
  Dockerfile              # Container image for the Streamlit app
  .env.example             # API_BASE_URL (required in container), API_TIMEOUT, STREAM_DEFAULT, CHAT_MODEL
  requirements.txt        # streamlit, httpx, python-dotenv (or uv/pyproject.toml)
  app/
    __init__.py
    main.py               # Streamlit entrypoint (streamlit run app/main.py)
    api.py                # Functions: health_check(), chat_completions(..., stream=...)
    config.py             # Load API_BASE_URL, API_TIMEOUT, STREAM_DEFAULT, CHAT_MODEL
```

Alternative: single-file app (`app.py`) if the team prefers minimal structure.

---

## 8. Acceptance criteria

1. User can open the app in a browser and see a chat interface.
2. User can type a message and send it; the message appears in history and the assistant reply is requested from `POST /v1/chat/completions`.
3. Assistant reply is displayed in the chat (streaming or not according to setting).
4. If streaming is on, the reply appears incrementally.
5. API errors (unreachable, 4xx, 5xx, timeout) are shown in the UI without crashing.
6. Health check (on load or via button) reflects API availability.
7. Configuration is driven by environment variables; in container, `API_BASE_URL` is set via env and not overridable in the UI.

---

## 9. Out of scope (explicit)

- User authentication / authorization.
- Storing chat history in a database or file.
- Calling agent tools directly from the UI (tools are used by the agent internally).
- Supporting the raw `POST /react-agent` endpoint as the main flow (optional extra only).

---

## 10. References

- API Usage document (base URL, `/health`, `/react-agent`, `/v1/chat/completions`, errors, CORS).
- Streamlit docs: [Chat elements](https://docs.streamlit.io/develop/api-reference/chat), [Session state](https://docs.streamlit.io/develop/concepts/state-management).
