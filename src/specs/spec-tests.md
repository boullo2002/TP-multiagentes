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
- multiple statements are blocked (incl. casos con comentarios tras `;` y comentarios antes de `SELECT`)
- SELECT with LIMIT is allowed

### 4.2 Memory stores

- persistent preferences read/write
- **schema context** read/write with version/timestamp y campos del artefacto (`context_markdown`, `schema_catalog`, etc.)
- short-term session store set/get

### 4.3 Validator

- flags unsafe SQL
- flags missing LIMIT when strict
- sugiere auto-fix de LIMIT cuando corresponde
- **no** se exige test de “HITL SQL al usuario”; el Query graph bloquea o reintenta según configuración

### 4.4 Graph wiring

- ambos grafos (Query y Schema) compilan
- Query graph: camino load → basic/plan → sql → validate → execute (y rama **retry** del validador cuando aplica)
- Schema flow puede setear `schema_hitl_pending` según borrador

---

## 5. Functional tests (minimum)

Using FastAPI `TestClient`:

- `GET /health` returns `healthy`
- `GET /tp-agent/playground` reachable
- `GET /schema-agent/playground` reachable (Schema graph)
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
