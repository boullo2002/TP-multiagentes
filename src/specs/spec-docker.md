# Specification — Docker-first (db + mcp + app + ui)

> **Purpose:** Setup reproducible para evaluación/demo: PostgreSQL con DVD Rental + servidor MCP + backend FastAPI/LangServe + **UI chat** (Open WebUI, patrón “OpenAIWeb” del curso).

---

## 1. Artefactos requeridos (repo)

En la raíz del repo deben existir (y coincidir con lo implementado):

| Artefacto | Rol |
| --- | --- |
| `Dockerfile` | Imagen **app** (FastAPI + LangGraph): `python:3.13-slim`, `uv`, `uvicorn`, `PYTHONPATH=/app/src` |
| `mcp_server/Dockerfile` | Imagen **mcp** (tools HTTP sobre Postgres) |
| `docker/db/Dockerfile` | Imagen **db**: `postgres:16` + **`unzip`** (necesario para `01_restore_dvdrental.sh`) |
| `docker-compose.yml` | Orquestación `db` + `mcp` + `app` + **`ui`** |
| `ui/README.md` | Notas sobre Open WebUI y variables |
| `.env.example` | Variables documentadas (Postgres, LLM, app, MCP, UI, etc.) |
| `docker/db/init/01_restore_dvdrental.sh` | Init: descomprime `db-data/dvdrental.zip` y hace `pg_restore` o `psql` |
| `db-data/dvdrental.zip` | Dataset obligatorio (en repo o montado localmente) |
| `pyproject.toml` | Dependencias; en build Docker se usa `uv sync` (idealmente con `uv.lock` versionado) |

**UI:** servicio Docker **`ui`** basado en **`ghcr.io/open-webui/open-webui`**, con `OPENAI_API_BASE_URLS=http://app:8000/v1` para usar este backend como API OpenAI-compatible. En el curso se suele llamar **OpenAIWeb** al patrón “cliente chat → `/v1/...`”; la implementación concreta aquí es Open WebUI.

---

## 2. Servicios en `docker-compose.yml` (estado actual)

### 2.1 `db` — PostgreSQL + DVD Rental

**Build:** `context: ./docker/db`, `dockerfile: Dockerfile` (Postgres 16 + `unzip`).

**Requisitos:**

- Variables: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (default `dvdrental`).
- Puerto host: `${POSTGRES_PORT:-5432}:5432`.
- Volúmenes:
  - `pgdata` → datos persistentes de Postgres
  - `./docker/db/init` → `/docker-entrypoint-initdb.d` (scripts de primera inicialización)
  - `./db-data` → `/db-data:ro` (zip del dataset)
- Healthcheck: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`

**Carga DVD Rental:**

- Fuente: `db-data/dvdrental.zip` montado en `/db-data/dvdrental.zip`.
- `01_restore_dvdrental.sh`:
  - descomprime con `unzip` en un directorio temporal
  - si hay `*.tar` → `pg_restore`
  - si hay `*.sql` → `psql -f`
  - carga en `POSTGRES_DB`

**Regla:** `db-data/dvdrental.zip` es la fuente canónica del dataset en este repo.

**Nota:** La primera vez que levantás el volumen `pgdata` vacío, Postgres ejecuta los scripts de `init`. Si ya tenías un `pgdata` sin datos cargados, puede hacer falta `docker compose down -v` y volver a subir.

---

### 2.2 `mcp` — MCP server (HTTP tools)

**Build:** `dockerfile: mcp_server/Dockerfile`, `context: .` (copia `pyproject.toml`, `mcp_server/`).

**Requisitos:**

- `DATABASE_URL=postgresql://user:pass@db:5432/<POSTGRES_DB>` (construida desde las mismas vars que `db`).
- `depends_on: db` con `condition: service_healthy`.
- Puerto: `7000:7000` (host y contenedor).
- Endpoints esperados por la app: `POST http://mcp:7000/tools/db_schema_inspect`, `POST .../tools/db_sql_execute_readonly`.

---

### 2.3 `app` — Backend (FastAPI + LangServe)

**Build:** `Dockerfile` en la raíz.

**Requisitos:**

- Variables típicas: `API_HOST`, `API_PORT`, `ENVIRONMENT`, `GRAPH_MAX_ITERATIONS`, `LLM_*`, `LANGSMITH_*`, `DATA_DIR` (default `/app/data`), `DEFAULT_LIMIT`, `SQL_SAFETY_STRICTNESS`, `MCP_SERVER_URL` (default `http://mcp:7000`), `MCP_REQUEST_TIMEOUT_MS`.
- `depends_on`: `db` healthy, `mcp` started.
- Puerto: `${API_PORT:-8000}:8000`.
- Volumen: `appdata` montado en `/app/data` (preferencias y descripciones de schema persistentes).
- **Healthcheck (compose):** `curl` a `http://127.0.0.1:8000/health` (para que `ui` espere con `service_healthy`).

**Comando:** `uv run uvicorn api.main:get_app --host 0.0.0.0 --port 8000`.

**Healthcheck (imagen):** además, el `Dockerfile` puede definir HEALTHCHECK equivalente.

---

### 2.4 `ui` — Open WebUI (patrón OpenAIWeb)

**Imagen:** `ghcr.io/open-webui/open-webui:main`.

**Requisitos:**

- `OPENAI_API_BASE_URLS=http://app:8000/v1` (base OpenAI-compatible; el backend expone `/v1/chat/completions`).
- `OPENAI_API_KEYS` vía `UI_OPENAI_API_KEY` (default `dummy` si el backend no valida la key).
- `WEBUI_SECRET_KEY` (sesión Open WebUI).
- `ENABLE_OLLAMA_API=false` (no usar Ollama embebido; solo el backend HTTP).
- `depends_on: app` con `condition: service_healthy`.
- Puerto host: `${UI_PORT:-3000}:8080` (Open WebUI escucha en **8080** dentro del contenedor).
- Volumen: `openwebui-data` → datos de la UI.

**Documentación:** `ui/README.md`.

---

## 3. `.env.example`

Debe incluir al menos:

- Postgres: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`
- App / grafo: `API_HOST`, `API_PORT`, `ENVIRONMENT`, `GRAPH_MAX_ITERATIONS`
- LLM: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
- LangSmith (opcional): `LANGSMITH_*`
- Almacenamiento y seguridad: `DATA_DIR`, `DEFAULT_LIMIT`, `SQL_SAFETY_STRICTNESS`
- MCP: `MCP_SERVER_URL`, `MCP_REQUEST_TIMEOUT_MS`
- UI: `UI_PORT`, `WEBUI_SECRET_KEY`, `UI_OPENAI_API_KEY`, `UI_ENABLE_SIGNUP`

---

## 4. Criterios de aceptación

1. `docker compose build` construye imágenes `db` (con `unzip`), `mcp` y `app`; descarga/tagea `ui` (Open WebUI).
2. `docker compose up` levanta `db` + `mcp` + `app` + `ui`.
3. Tras init, en `db` existen tablas del DVD Rental (`psql ... \\dt`).
4. `GET http://localhost:<API_PORT>/health` responde `healthy`.
5. El backend puede llamar al MCP en `MCP_SERVER_URL` y ejecutar tools.
6. La UI en `http://localhost:<UI_PORT>` puede chatear vía Open WebUI usando el backend como API OpenAI-compatible (`/v1/chat/completions`).

---

## 5. Comandos útiles

```bash
docker compose up --build
docker compose exec db psql -U dvd_user -d dvdrental -c "\\dt"
curl -s http://localhost:8000/health
```
