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

### Memoria (spec-memory)

Persistente (`DATA_DIR`, p. ej. `/app/data` en Docker):

- **`user_preferences.json`**: preferencias entre sesiones — idioma (`preferred_language`, default `es`), formato de salida (`preferred_output_format`: `table` o `json`), formato de fechas (`preferred_date_format`), `sql_safety_strictness` y `default_limit`. Influyen en prompts, límites sugeridos y frecuencia de HITL.
- **`schema_descriptions.json`**: descripciones de tablas/columnas aprobadas vía HITL, con `version`, `generated_at` y payload `tables` (más `relationships_summary` si aplica). El Query Agent las reutiliza para NL→SQL.

Corto plazo (misma sesión / mismo `session_id`):

- Campo **`short_term`** en el estado del grafo y copia en un **`SessionStore`** en memoria: última pregunta, último borrador SQL y SQL ejecutado, tablas recientes, filtros heurísticos (p. ej. años), supuestos del plan y preview del último resultado. Sirve para seguimientos del tipo “solo 2006” o “orden descendente”.

