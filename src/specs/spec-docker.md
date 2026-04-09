# Specification — Docker-first (db + app + mcp + ui)

> **Purpose:** Ensure fully reproducible setup for evaluation/demo: PostgreSQL with DVD Rental loaded + backend API + MCP server + OpenAIWeb UI, all via Docker Compose.

---

## 1. Required artifacts

At repo root:

- `Dockerfile` (backend)
- `docker-compose.yml`
- `.env.example`
- `docker/db/init/01_restore_dvdrental.sh`

Optional:

- `ui/Dockerfile` (if OpenAIWeb is built from source inside this repo)

---

## 2. Services in docker-compose

### 2.1 `db` — PostgreSQL + DVD Rental

Requirements:

- image `postgres:16` (or stable version used in class)
- env:
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
  - `POSTGRES_DB` (default `dvdrental`)
- volumes:
  - `pgdata:/var/lib/postgresql/data`
  - `./docker/db/init:/docker-entrypoint-initdb.d:ro`
  - `./db-data:/db-data:ro`
- healthcheck with `pg_isready`

DVD Rental loading:

- the repository provides `db-data/dvdrental.zip`
- init script `01_restore_dvdrental.sh` must:
  - locate `/db-data/dvdrental.zip`
  - unzip it to a temp directory inside the container
  - detect:
    - `dvdrental.tar` inside the zip (preferred) and run `pg_restore`, OR
    - a `.sql` file and run it via `psql`
  - load into `POSTGRES_DB`

**Rule:** `db-data/dvdrental.zip` is the single source of truth for the dataset in this repo.

### 2.2 `mcp` — MCP server

Requirements:

- built from `mcp_server/` (Dockerfile optional, can reuse root image)
- env:
  - `DATABASE_URL=postgresql://...@db:5432/dvdrental`
- depends_on:
  - `db` healthy
- exposed port internal (e.g. `7000`)

### 2.3 `app` — FastAPI + LangServe backend

Requirements:

- built from repo root `Dockerfile`
- env:
  - `API_HOST=0.0.0.0`
  - `API_PORT=8000`
  - `MCP_SERVER_URL=http://mcp:7000`
  - LLM settings `LLM_*`
  - `DATA_DIR=/app/data`
- depends_on:
  - `db` healthy
  - `mcp` started
- port mapping:
  - `8000:8000`

### 2.4 `ui` — OpenAIWeb

Requirements:

- either:
  - run OpenAIWeb as a container image used in class, or
  - build from `ui/` (if included in repo)
- env:
  - `API_BASE_URL=http://app:8000`
  - `OPENAI_API_KEY=dummy` (if required)
- depends_on:
  - `app`
- port mapping:
  - `3000:3000` (or the port OpenAIWeb uses)

---

## 3. `.env.example` (minimum)

Include:

- Postgres vars
- LLM vars
- app vars (API, graph max iterations, defaults)
- MCP vars
- UI vars (API_BASE_URL)

---

## 4. Acceptance criteria

1. `docker compose up --build` brings up db + mcp + app (+ ui if included).
2. DVD Rental schema is available in db (tables exist).
3. Backend `/health` is reachable.
4. UI can call `/v1/chat/completions` and chat.

