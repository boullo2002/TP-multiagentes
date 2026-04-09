# Specification — Testing (pytest) + Lint/Format (ruff)

> **Purpose:** Define required unit + functional tests and quality gates, matching class demo style (plain pytest functions + ruff).

---

## 1. Tooling

- `pytest` for unit + functional tests
- `ruff` for lint + format
- `python-dotenv` for loading `.env` in tests (as in demos)

---

## 2. Testing style

All tests must be **plain pytest functions** (no classes) and follow:

- Given / When / Then / Clean

---

## 3. Test fixtures (`tests/conftest.py`)

Load `.env` from repo root **before importing app modules**:

- use `load_dotenv()`
- assert load is successful

Also provide fixtures:

- `client`: FastAPI TestClient
- `settings`: loaded settings object

---

## 4. Unit tests (minimum)

Create tests for:

### 4.1 SQL safety

- unsafe keywords are blocked
- multiple statements are blocked
- SELECT with LIMIT is allowed

### 4.2 Memory stores

- persistent preferences read/write
- schema descriptions read/write with version/timestamp
- short-term session store set/get

### 4.3 Validator

- flags unsafe SQL
- flags missing LIMIT when strict
- requests HITL for risky queries

### 4.4 Graph wiring

- graph compiles
- router chooses schema vs query for representative inputs
- schema flow sets HITL pending
- query flow produces SQL draft then runs validator before execute

---

## 5. Functional tests (minimum)

Using FastAPI `TestClient`:

- `GET /health` returns `healthy`
- `GET /tp-agent/playground` reachable
- `POST /tp-agent/invoke` returns runnable response (with a mocked LLM if needed)
- `POST /v1/chat/completions` returns OpenAI-compatible response shape

Optional (recommended) integration tests if DB available in CI:

- schema inspect via MCP tool returns expected keys
- read-only SQL execution via MCP returns rows for a known safe query

---

## 6. Commands (document in README)

- Install:
  - `uv sync`
- Lint/format:
  - `uv run ruff check --fix`
  - `uv run ruff format`
- Test:
  - `uv run pytest`

---

## 7. Acceptance criteria

1. `uv run ruff check` passes.
2. `uv run ruff format` produces no diffs.
3. `uv run pytest` passes (unit + functional).

