# OpenAIWeb / Open WebUI — cliente OpenAI-compatible

Implementación del patrón **OpenAIWeb** del curso: la UI es solo un cliente de chat; el backend FastAPI ejecuta LangGraph, agentes, MCP y HITL.

**Imagen:** [Open WebUI](https://github.com/open-webui/open-webui) en Docker.

---

## 1. Alcance

- Enviar mensajes al backend y mostrar respuestas del asistente (SQL, previews, explicaciones; suele renderizar **markdown** y bloques de código).
- **HITL por chat**: aprobar o pegar correcciones cuando el backend lo pide (schema o SQL).
- Fuera de alcance (según spec): autenticación “de entrega”, persistencia de historial como requisito, invocación directa de tools desde la UI.

---

## 2. Stack

| Capa | Rol |
| --- | --- |
| **Open WebUI** | Cliente HTTP hacia API tipo OpenAI |
| **Backend (`app`)** | `GET /health`, `GET /v1/models`, `POST /v1/chat/completions` (JSON o SSE si `stream: true`) |
| **Docker Compose** | Servicios `app` + `ui` en la misma red (`ui` → `http://app:8000/v1/...`) |

---

## 3. Configuración por entorno

La URL del backend **no** debe configurarse solo desde controles en runtime: va por variables de entorno del contenedor. En el compose usamos `ENABLE_PERSISTENT_CONFIG=false` para que los valores del entorno no queden pisados por SQLite tras el primer arranque.

### 3.1 Mapeo spec ↔ variables reales (Open WebUI)

El spec (`spec-ui-openaiweb.md`) nombra variables genéricas; en Open WebUI los nombres oficiales son otros:

| Spec | Requerido (contenedor) | Default sugerido | Variable / valor en este repo |
| --- | --- | --- | --- |
| `API_BASE_URL` | **sí** (concepto: origen del backend **sin** path `/v1`) | — | En Compose: host lógico `http://app:8000`. La URL que consume Open WebUI incluye **`/v1`**: equivale a `OPENAI_API_BASE_URLS` |
| `OPENAI_API_KEY` | no | `dummy` | `OPENAI_API_KEYS` ← `UI_OPENAI_API_KEY` en `.env` (el backend suele **no** validarla) |
| `DEFAULT_MODEL` | no | `tp-multiagentes` | No hay env dedicado: el listado viene de **`GET /v1/models`**; elegí el modelo **`tp-multiagentes`** en el selector |

**Equivalencia importante**

- **Spec:** `API_BASE_URL=http://app:8000`
- **Open WebUI:** base de la API OpenAI = `{API_BASE_URL}/v1` → p. ej. `http://app:8000/v1`

Variable de entorno en este proyecto (sobrescribible en `.env`):

| Variable | Descripción |
| --- | --- |
| `UI_OPENAI_API_BASE_URLS` | Una o más URLs base con **`/v1`**, separadas por `;` si hiciera falta. Default en compose: `http://app:8000/v1` |
| `UI_OPENAI_API_KEY` | Key enviada en cabeceras hacia tu backend (`/v1/...`) |
| `UI_PORT` | Puerto publicado en el host (default **3000** → contenedor escucha en 8080) |
| `WEBUI_SECRET_KEY` | Secreto de sesión de Open WebUI |
| `UI_ENABLE_SIGNUP` | Registro local en la UI (`true`/`false`) |

### 3.2 Arranque

Desde la raíz del repo:

```bash
docker compose up --build
```

Abrí **`http://localhost:${UI_PORT:-3000}`**. El primer arranque de Open WebUI puede tardar (descarga de imagen, init).

---

## 4. Uso de la API (lo que hace la UI por detrás)

### 4.1 Health (recomendado para depurar)

- **Request:** `GET {API_BASE_URL}/health`
- **Ejemplo desde el host** (con `API_PORT=8000`):

```bash
curl -fsS http://127.0.0.1:8000/health
```

También podés usar el script `ui/verify-backend.sh` (misma comprobación).

### 4.2 Chat (obligatorio)

- **Request:** `POST {API_BASE_URL}/v1/chat/completions`
- **Body típico:** `model`, `messages` (`role` + `content`), `stream` (`true` = SSE, `false` = JSON completo).

Open WebUI mantiene el historial de la conversación y lo reenvía en `messages` si está habilitado en la app.

---

## 5. HITL vía chat

Cuando el backend pide aprobación humana, el mensaje del asistente incluye instrucciones claras y un identificador:

- `HITL_CHECKPOINT_ID=<uuid>`
- Tipo: `HITL_KIND=schema_descriptions` o `HITL_KIND=sql_execution`

**Respuesta del usuario**

- Escribí **`APPROVE`** (sin distinguir mayúsculas) para aceptar el borrador tal cual.
- Cualquier otro texto se interpreta como **versión editada** (JSON de descripciones o SQL `SELECT`, según el flujo).

---

## 6. Errores y estado de conexión

| Situación | Qué ver / qué hacer |
| --- | --- |
| Backend caído o red | Open WebUI suele mostrar error de conexión o timeout al enviar el mensaje. Verificá `docker compose ps`, logs de `app` y `curl` a `/health`. |
| MCP no disponible | El backend puede responder **503** en chat con mensaje de servicio de datos; revisá el contenedor `mcp` y `MCP_SERVER_URL`. |
| 4xx en SQL (MCP) | Mensaje amigable en la respuesta del asistente con detalle acotado. |
| Modelo vacío o incorrecto | En la UI elegí **`tp-multiagentes`** (listado vía `GET /v1/models`). |

---

## 7. Criterios de aceptación (checklist)

1. Abrir Open WebUI y acceder al chat.
2. Enviar un mensaje dispara `POST /v1/chat/completions` hacia el backend (comprobar logs de `app` o proxy).
3. La respuesta se muestra en el hilo; markdown y bloques de código (p. ej. SQL) suelen renderizarse bien.
4. HITL: responder `APPROVE` o pegar corrección según el mensaje del asistente.
5. Fallos de red o HTTP: visibles en la UI o en logs; usar `/health` y la sección anterior para diagnosticar.
