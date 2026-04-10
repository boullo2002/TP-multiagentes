# UI — Open WebUI (patrón OpenAIWeb)

Este proyecto usa la imagen oficial **[Open WebUI](https://github.com/open-webui/open-webui)** como interfaz de chat: habla con el backend FastAPI por el endpoint **OpenAI-compatible** (`POST /v1/chat/completions`).

En varios materiales del curso se nombra **OpenAIWeb**; aquí la implementación concreta es **Open WebUI en Docker**, apuntando a `http://app:8000/v1` dentro de la red de Compose.

## Uso

1. Levantá el stack: `docker compose up --build` (desde la raíz del repo). El primer arranque de Open WebUI puede tardar mientras descarga modelos auxiliares (p. ej. embeddings para RAG); el chat contra tu backend usa `POST /v1/chat/completions` y no pasa por LiteLLM en la UI.
2. Abrí en el navegador: `http://localhost:${UI_PORT:-3000}` (por defecto puerto **3000**).
3. En el primer acceso podés crear cuenta local (según `UI_ENABLE_SIGNUP`) o seguir el flujo que muestre la UI.
4. En **Settings → Connections** (o equivalente), confirmá que el proveedor OpenAI apunta a tu backend (`OPENAI_API_BASE_URLS` ya se inyecta por entorno hacia `http://app:8000/v1`).

## Si no aparecen modelos en el selector

1. Reconstruí el backend después de cambios de código: `docker compose up -d --build app` (o `--build` en todo el stack). Sin rebuild, el contenedor puede seguir sin `GET /v1/models`.
2. El volumen `openwebui-data` puede haber guardado una conexión vieja. Con `ENABLE_PERSISTENT_CONFIG=false` en `docker-compose` (servicio `ui`) se fuerza a usar `OPENAI_API_BASE_URLS` / `OPENAI_API_KEYS` del compose. Alternativa: borrar el volumen (perdés usuarios/chats de la UI).

## Variables (ver `.env.example`)

| Variable | Descripción |
| --- | --- |
| `UI_PORT` | Puerto en el host (default `3000`) |
| `WEBUI_SECRET_KEY` | Clave de sesión de Open WebUI (cambiar en producción) |
| `UI_OPENAI_API_KEY` | Key que Open WebUI manda a **tu API** (`/v1/...`). No es `LLM_API_KEY`: esa es la que usa el **servicio `app`** para llamar al proveedor LLM. |
| `UI_ENABLE_SIGNUP` | `true`/`false` — registro de usuarios en la UI |
