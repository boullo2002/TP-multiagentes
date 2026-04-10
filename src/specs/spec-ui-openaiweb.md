# OpenAIWeb UI — Specification (OpenAI-compatible client)

> **Purpose:** Provide a dockerized UI client (OpenAIWeb) configured to chat with the TP backend via an OpenAI-compatible endpoint, matching the class pattern where the UI is a client and the backend does all agent orchestration.

---

## 1. Purpose and scope

- **Purpose**: Provide a UI to:
  - send chat messages to the backend
  - display assistant responses (including SQL + previews + explanations)
  - support HITL **via chat** (approve/edit schema descriptions; approve risky SQL)
- **Scope**:
  - One OpenAIWeb deployment (dockerized) configured by env vars
  - Calls backend endpoints:
    - `GET /health`
    - `POST /v1/chat/completions`

Out of scope:

- Authentication
- Persisting chat history as a graded requirement
- Direct tool invocation from the UI

---

## 2. Tech stack

- **UI**: OpenAIWeb (same as class usage)
- **Backend**: FastAPI + LangServe exposing OpenAI-compatible chat completions
- **Deployment**: Docker Compose

---

## 3. Configuration

### 3.1 Environment variables

All UI configuration is env-driven. In containers, the backend URL **must** be set via env.

Document these variables (names may vary slightly by OpenAIWeb version; keep a mapping in `ui/README.md`):

| Variable | Required (container) | Default | Description |
| --- | --- | --- | --- |
| `API_BASE_URL` | **yes** | *(none)* | Backend base URL, e.g. `http://app:8000` |
| `OPENAI_API_KEY` | no | `dummy` | Dummy key if required by UI; backend may ignore |
| `DEFAULT_MODEL` | no | `tp-multiagentes` | Model label shown in the UI |

### 3.2 Container deployment

- UI must not require configuring the base URL via UI controls at runtime.
- UI must run in Docker and be reachable on a stable port (e.g. `3000`).

---

## 4. API usage

### 4.1 Health check (recommended)

- **Endpoint**: `GET {API_BASE_URL}/health`
- **Use**: show connection status / help debugging

### 4.2 Chat (required)

- **Endpoint**: `POST {API_BASE_URL}/v1/chat/completions`
- **Request body**:
  - `model`: string
  - `messages`: array of `{ role, content }`
  - `stream`: boolean (backend supports **streaming** SSE when `true`; non-streaming JSON when `false`)

The UI should send full message history if it already does so.

---

## 5. HITL interaction design (via chat)

Because OpenAIWeb is a generic chat UI, HITL is implemented conversationally:

- When the backend needs approval, it returns an assistant message containing:
  - clear instructions (“Reply with APPROVE or paste corrections”)
  - a checkpoint id:
    - `HITL_CHECKPOINT_ID=<uuid>`
  - the draft content (schema descriptions or SQL)

User replies:

- `APPROVE` (case-insensitive) to approve
- otherwise the message is treated as the edited version

---

## 6. Acceptance criteria

1. User can open OpenAIWeb and access a chat UI.
2. Sending a message triggers `POST /v1/chat/completions` to the backend.
3. Assistant response is displayed and may render markdown/code blocks.
4. HITL approvals/edits can be performed via chat.
5. Backend unreachable/4xx/5xx/timeouts are shown clearly.

