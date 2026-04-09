## TP Multiagentes (DVD Rental NLQ) — Docker-first

Este proyecto implementa la consigna de `task.md` usando:

- LangGraph (StateGraph) con nodos/edges/routing explícitos
- 2 agentes: Schema Agent + Query Agent
- MCP tools (server separado): inspección de schema + ejecución SQL read-only
- Memoria persistente + memoria de corto plazo
- HITL (aprobación/edición por chat) + validator/critic
- FastAPI + LangServe + adapter OpenAI-compatible `/v1/chat/completions`
- **UI (Open WebUI)** en Docker, conectada al backend como cliente OpenAI-compatible (ver `ui/README.md`)

### Requisitos

- Docker + Docker Compose
- Variables LLM (OpenAI-compatible): `LLM_BASE_URL`, `LLM_API_KEY`

### Levantar todo

1. Copiar env:

```bash
cp .env.example .env
```

2. Build + up:

```bash
docker compose up --build
```

### Verificar DB (DVD Rental)

```bash
docker compose exec db psql -U dvd_user -d dvdrental -c "\\dt"
```

### Probar backend

- Health: `GET http://localhost:8000/health`
- LangServe playground: `GET http://localhost:8000/tp-agent/playground`
- OpenAI-compatible: `POST http://localhost:8000/v1/chat/completions`

### UI (Open WebUI)

Con todo levantado (`docker compose up --build`):

- Abrí **`http://localhost:3000`** (o el puerto que definas en `UI_PORT`).
- El contenedor `ui` usa `OPENAI_API_BASE_URLS=http://app:8000/v1` para hablar con este mismo repo como API tipo OpenAI.

Detalle: `ui/README.md`.

### Tests / lint (local)

```bash
uv sync
uv run ruff check --fix
uv run ruff format
uv run pytest
```

