from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from starlette.responses import HTMLResponse, StreamingResponse

import api.openai_graph as openai_graph
from app_logging import configure_langsmith, configure_logging
from config.settings import get_settings
from contracts.openai_compat import (
    ChatCompletionsRequest,
    ChatCompletionsResponse,
    ChatCompletionsResponseChoice,
    ChatMessage,
)
from graph.query_workflow import get_compiled_query_graph
from graph.schema_workflow import get_compiled_schema_graph
from services.schema_context_service import run_schema_context_generation

logger = logging.getLogger(__name__)

_STREAM_CHUNK_CHARS = 48
_STREAM_KEEPALIVE_SEC = 12.0

_MCP_UNAVAILABLE_MSG = (
    "No se pudo conectar al servicio de datos (MCP). "
    "Verificá que el contenedor `mcp` esté en línea y que `MCP_SERVER_URL` sea correcto."
)


# Compat para tests/monkeypatch y llamadas existentes.
def get_compiled_graph():
    return get_compiled_query_graph()


def _sse_chat_chunk(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: dict,
    finish_reason: str | None,
) -> bytes:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


async def _stream_chat_completion(*, req: ChatCompletionsRequest) -> StreamingResponse:
    completion_id = f"chatcmpl-{uuid.uuid4()}"
    created = int(time.time())
    model = req.model

    async def event_gen():
        yield _sse_chat_chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant", "content": ""},
            finish_reason=None,
        )
        task: asyncio.Task[str] = asyncio.create_task(
            asyncio.to_thread(openai_graph.invoke_graph_for_chat_request, req.messages)
        )
        try:
            while True:
                done, _ = await asyncio.wait(
                    {task}, timeout=_STREAM_KEEPALIVE_SEC, return_when=asyncio.FIRST_COMPLETED
                )
                if task in done:
                    break
                yield b": keepalive\n\n"
            content = task.result()
        except Exception as e:
            logger.exception("stream_graph_failed")
            if openai_graph.is_mcp_unavailable(e):
                err_text = _MCP_UNAVAILABLE_MSG
                yield _sse_chat_chunk(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    delta={"content": err_text},
                    finish_reason=None,
                )
                yield _sse_chat_chunk(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    delta={},
                    finish_reason="stop",
                )
                yield b"data: [DONE]\n\n"
                return
            fallback = openai_graph.stream_fallback_assistant_text(e)
            err_text = fallback or "No pude completar la respuesta. Probá de nuevo."
            yield _sse_chat_chunk(
                completion_id=completion_id,
                created=created,
                model=model,
                delta={"content": err_text},
                finish_reason=None,
            )
            yield _sse_chat_chunk(
                completion_id=completion_id,
                created=created,
                model=model,
                delta={},
                finish_reason="stop",
            )
            yield b"data: [DONE]\n\n"
            return

        for i in range(0, len(content), _STREAM_CHUNK_CHARS):
            piece = content[i : i + _STREAM_CHUNK_CHARS]
            yield _sse_chat_chunk(
                completion_id=completion_id,
                created=created,
                model=model,
                delta={"content": piece},
                finish_reason=None,
            )
        yield _sse_chat_chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={},
            finish_reason="stop",
        )
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def get_app() -> FastAPI:
    configure_logging()
    configure_langsmith()
    settings = get_settings()

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "healthy", "environment": settings.app.environment}

    @app.get("/v1/models")
    def list_models() -> dict:
        default_id = "tp-multiagentes"
        llm_id = (settings.llm.model or "").strip() or default_id
        ids: list[str] = []
        for mid in (default_id, llm_id):
            if mid and mid not in ids:
                ids.append(mid)
        now = int(time.time())
        return {
            "object": "list",
            "data": [
                {"id": mid, "object": "model", "created": now, "owned_by": "tp-multiagentes"}
                for mid in ids
            ],
        }

    runnable = get_compiled_graph()
    add_routes(app, runnable, path="/tp-agent")

    schema_runnable = get_compiled_schema_graph()
    add_routes(app, schema_runnable, path="/schema-agent")

    @app.get("/schema")
    def schema_front() -> dict:
        # Front mínimo: el playground de LangServe es la UI del Schema Agent.
        return {"open": "/schema-agent/playground"}

    @app.on_event("startup")
    def ensure_schema_context_on_startup() -> None:
        try:
            out = run_schema_context_generation(force=False)
            logger.info("schema_context_startup status=%s hash=%s", out.status, out.schema_hash)
        except Exception:
            logger.exception("schema_context_startup_failed")

    @app.get("/schema-agent/state")
    def schema_agent_state() -> dict:
        out = run_schema_context_generation(force=False)
        return {
            "status": out.status,
            "schema_hash": out.schema_hash,
            "context": out.context,
            "draft": out.draft,
        }

    @app.post("/schema-agent/run")
    def schema_agent_run(payload: dict | None = None) -> dict:
        body = payload or {}
        force = bool(body.get("force", True))
        out = run_schema_context_generation(force=force)
        return {
            "status": out.status,
            "schema_hash": out.schema_hash,
            "context": out.context,
            "draft": out.draft,
        }

    @app.post("/schema-agent/answer")
    def schema_agent_answer(payload: dict) -> dict:
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise HTTPException(status_code=400, detail="`answers` debe ser un objeto JSON.")
        out = run_schema_context_generation(force=True, answers=answers)
        return {
            "status": out.status,
            "schema_hash": out.schema_hash,
            "context": out.context,
            "draft": out.draft,
        }

    @app.get("/schema-agent/ui", response_class=HTMLResponse)
    def schema_agent_ui() -> str:
        return """<!doctype html>
<html lang="es"><head><meta charset="utf-8"/><title>Schema Agent UI</title>
<style>
body{font-family:system-ui,Arial;margin:20px;max-width:1100px}
button{margin-right:8px}
textarea{width:100%;height:120px}
pre{background:#111;color:#ddd;padding:12px;overflow:auto}
.row{display:flex;gap:16px}
.col{flex:1}
.chat{
  border:1px solid #ddd;border-radius:8px;padding:12px;min-height:260px;
  max-height:420px;overflow:auto;background:#fafafa
}
.msg{padding:10px 12px;border-radius:10px;margin:8px 0;max-width:90%}
.assistant{background:#eaf3ff;border:1px solid #c9defd}
.user{background:#eafbea;border:1px solid #c9efc8;margin-left:auto}
.status-pill{display:inline-block;padding:4px 8px;border-radius:999px;font-size:12px}
.ok{background:#e7f7ec;color:#0a7f2e}
.warn{background:#fff3e8;color:#b35c00}
.muted{color:#666;font-size:13px}
</style></head><body>
<h2>Schema Agent UI</h2>
<p>Estado: <span id="statusPill" class="status-pill">-</span> | Hash: <code id="hash">-</code></p>
<p class="muted">
  Si hay ambigüedad, el estado aparece como <b>needs_human</b> y se listan preguntas abajo.
</p>
<button onclick="refreshState()">Refrescar estado</button>
<button onclick="runAgent()">Regenerar contexto</button>

<div class="row">
  <div class="col">
    <h3>Chat Schema Agent</h3>
    <div id="chat" class="chat"></div>
    <textarea id="chatInput" placeholder='Escribí APPROVE o JSON {"q1":"..."}'></textarea><br/>
    <button onclick="sendChat()">Enviar</button>
  </div>
  <div class="col">
    <h3>Preguntas ambiguas detectadas</h3>
    <pre id="questions">[]</pre>
    <h3>Salida técnica</h3>
    <pre id="out">{}</pre>
  </div>
</div>

<script>
let currentState = null;

function addMsg(role, text){
  const c = document.getElementById('chat');
  const d = document.createElement('div');
  d.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
  d.textContent = text;
  c.appendChild(d);
  c.scrollTop = c.scrollHeight;
}

function summarizeAssistant(j){
  if (!j) return 'Sin datos';
  if (j.status === 'ready'){
    return 'Contexto listo. El Query Agent ya puede usar schema_context.json.';
  }
  if (j.status === 'needs_human'){
    return 'Hay ambigüedades. Respondé con JSON de answers o APPROVE si está bien.';
  }
  return 'Estado actualizado.';
}

async function refreshState(){
  const r = await fetch('/schema-agent/state');
  const j = await r.json();
  render(j);
}
async function runAgent(){
  const r = await fetch('/schema-agent/run', {
    method: 'POST',
    headers: {'content-type':'application/json'},
    body: JSON.stringify({force:true}),
  });
  const j = await r.json();
  render(j);
  addMsg('assistant', summarizeAssistant(j));
}
async function sendChat(){
  const input = document.getElementById('chatInput');
  const raw = input.value.trim();
  if (!raw) return;
  addMsg('user', raw);
  input.value = '';

  if (raw.toUpperCase() === 'APPROVE'){
    const j = await (await fetch('/schema-agent/run', {
      method: 'POST',
      headers: {'content-type':'application/json'},
      body: JSON.stringify({force:true}),
    })).json();
    render(j);
    addMsg('assistant', summarizeAssistant(j));
    return;
  }

  let answers = null;
  try {
    const parsed = JSON.parse(raw);
    answers = parsed.answers ? parsed.answers : parsed;
  } catch(e){
    addMsg(
      'assistant',
      'Formato inválido. Enviá APPROVE o un JSON válido (ej: {"q1":"Año de lanzamiento"}).'
    );
    return;
  }
  const j = await (await fetch('/schema-agent/answer', {
    method: 'POST',
    headers: {'content-type':'application/json'},
    body: JSON.stringify({answers}),
  })).json();
  render(j);
  addMsg('assistant', summarizeAssistant(j));
}
function render(j){
  currentState = j;
  const s = j.status || '-';
  const pill = document.getElementById('statusPill');
  pill.textContent = s;
  pill.className = 'status-pill ' + (s === 'ready' ? 'ok' : 'warn');
  document.getElementById('hash').textContent = j.schema_hash || '-';
  const qs = (j.draft && j.draft.questions) ? j.draft.questions : [];
  document.getElementById('questions').textContent = JSON.stringify(qs, null, 2);
  document.getElementById('out').textContent = JSON.stringify(j, null, 2);
}
refreshState();
</script></body></html>"""

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionsRequest):
        if req.stream:
            return await _stream_chat_completion(req=req)

        try:
            content = await asyncio.to_thread(
                openai_graph.invoke_graph_for_chat_request,
                req.messages,
            )
        except Exception as e:
            if openai_graph.is_mcp_unavailable(e):
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "mcp_unavailable",
                        "message": _MCP_UNAVAILABLE_MSG,
                    },
                ) from e
            # Errores de grafo/LLM: respuesta 200 con texto amable (evitar error rojo en la UI).
            content = openai_graph.stream_fallback_assistant_text(e) or (
                "No pude completar la respuesta. Probá de nuevo en unos segundos."
            )

        return ChatCompletionsResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            created=int(time.time()),
            model=req.model,
            choices=[
                ChatCompletionsResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
        )

    return app
