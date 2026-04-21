from __future__ import annotations

import json
import os
from typing import Any

import httpx
import streamlit as st

BACKEND_URL = os.getenv("SCHEMA_AGENT_BACKEND_URL", "http://app:8000").rstrip("/")


def _get(path: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{BACKEND_URL}{path}")
        r.raise_for_status()
        return r.json()


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=120.0) as c:
        r = c.post(f"{BACKEND_URL}{path}", json=payload)
        r.raise_for_status()
        return r.json()


def _safe_refresh() -> None:
    try:
        st.session_state["last"] = _get("/schema-agent/state")
        st.session_state["last_error"] = None
    except Exception as e:
        st.session_state["last_error"] = f"No se pudo obtener el estado: {e}"


def _safe_run(force: bool = True) -> None:
    try:
        st.session_state["last"] = _post("/schema-agent/run", {"force": force})
        st.session_state["last_error"] = None
    except Exception as e:
        st.session_state["last_error"] = f"No se pudo regenerar contexto: {e}"


def _safe_submit_answers(answers: dict[str, Any]) -> None:
    try:
        st.session_state["last"] = _post("/schema-agent/answer", {"answers": answers})
        st.session_state["last_error"] = None
    except Exception as e:
        st.session_state["last_error"] = f"No se pudieron enviar respuestas: {e}"


def _submit_free_text_note(note: str, data: dict[str, Any]) -> None:
    existing_answers = data.get("context", {}).get("answers", {})
    notes: list[str] = []
    if isinstance(existing_answers, dict):
        prev_notes = existing_answers.get("extra_notes")
        if isinstance(prev_notes, list):
            notes = [str(x) for x in prev_notes if str(x).strip()]
    notes.append(note.strip())
    payload = {"extra_notes": notes, "extra_input": note.strip()}
    _safe_submit_answers(payload)


def _status_meta(status: str) -> tuple[str, str, str]:
    if status == "ready":
        return ("Listo", "#22c55e", "El contexto ya esta disponible para el Query Agent.")
    if status == "needs_human":
        return ("Necesita revision humana", "#f59e0b", "Hay ambiguedades pendientes para resolver.")
    return ("Sin estado", "#64748b", "Todavia no hay informacion completa del flujo.")


def _render_chat_bubble(role: str, content: str) -> None:
    css_class = "bubble-user" if role == "user" else "bubble-assistant"
    who = "Vos" if role == "user" else "Schema Agent"
    st.markdown(
        f"""
<div class="chat-row {css_class}">
  <div class="chat-role">{who}</div>
  <div>{content}</div>
</div>
""",
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="Schema Agent", layout="wide")
st.markdown(
    """
<style>
.stApp { background: #f8fafc; }
.hero {
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 45%, #0b4a6f 100%);
  border-radius: 16px;
  padding: 20px 22px;
  color: white;
  margin-bottom: 14px;
  border: 1px solid rgba(255,255,255,.08);
}
.hero h1 { margin: 0 0 6px 0; font-size: 1.7rem; }
.hero p { margin: 0; color: #dbeafe; }
.status-pill {
  display: inline-block;
  padding: 6px 12px;
  border-radius: 999px;
  color: white;
  font-weight: 600;
  font-size: 0.86rem;
}
.soft-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px 14px;
}
.chat-row {
  border-radius: 12px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid #e2e8f0;
}
.bubble-user {
  background: #eff6ff;
  margin-left: 8%;
}
.bubble-assistant {
  background: #f8fafc;
  margin-right: 8%;
}
.chat-role {
  font-size: .78rem;
  color: #334155;
  margin-bottom: 2px;
  font-weight: 600;
}
</style>
""",
    unsafe_allow_html=True,
)

if "last" not in st.session_state:
    _safe_refresh()
if "last_error" not in st.session_state:
    st.session_state["last_error"] = None
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

data = st.session_state.get("last") or {}
status = str(data.get("status", "-"))
schema_hash = str(data.get("schema_hash", "-"))
draft = data.get("draft") or {}
context_obj = data.get("context") or {}
context_md = str(draft.get("context_markdown") or context_obj.get("context_markdown") or "")
questions = draft.get("questions") if isinstance(draft.get("questions"), list) else []
existing_answers = context_obj.get("answers", {}) if isinstance(context_obj, dict) else {}
if not isinstance(existing_answers, dict):
    existing_answers = {}

answered_count = 0
for i, q in enumerate(questions, start=1):
    qid = str(q.get("id") or f"q{i}")
    value = existing_answers.get(qid)
    if isinstance(value, str) and value.strip():
        answered_count += 1
    elif value not in (None, ""):
        answered_count += 1

completion_ratio = (answered_count / len(questions)) if questions else 1.0
status_label, status_color, status_hint = _status_meta(status)

st.markdown(
    f"""
<div class="hero">
  <h1>Schema Agent Workspace</h1>
  <p>Un flujo visual para resolver ambiguedades, aportar contexto y publicar un schema context confiable.</p>
</div>
""",
    unsafe_allow_html=True,
)

top_c1, top_c2, top_c3, top_c4 = st.columns([2.2, 1, 1, 1])
with top_c1:
    st.markdown(
        f'<span class="status-pill" style="background:{status_color};">{status_label}</span>',
        unsafe_allow_html=True,
    )
    st.caption(status_hint)
with top_c2:
    st.metric("Preguntas", str(len(questions)))
with top_c3:
    st.metric("Respondidas", str(answered_count))
with top_c4:
    short_hash = schema_hash[:12] + "..." if len(schema_hash) > 15 else schema_hash
    st.metric("Schema hash", short_hash)

with st.sidebar:
    st.subheader("Panel rapido")
    if status == "needs_human":
        st.warning("Siguiente paso: responder preguntas.")
    else:
        st.success("Siguiente paso: revisar contexto final.")
    st.progress(completion_ratio, text=f"Progreso {answered_count}/{len(questions)}")
    if st.button("Refrescar estado", use_container_width=True):
        with st.spinner("Refrescando estado..."):
            _safe_refresh()
        st.rerun()
    if st.button("Regenerar contexto", use_container_width=True):
        with st.spinner("Regenerando borrador..."):
            _safe_run(force=True)
        st.rerun()
    if st.button("Aprobar sin cambios", use_container_width=True):
        with st.spinner("Aprobando..."):
            _safe_run(force=True)
        st.rerun()
    st.caption("El modo avanzado esta al final para debugging.")

if st.session_state.get("last_error"):
    st.error(st.session_state["last_error"])

tab_chat, tab_questions, tab_context, tab_advanced = st.tabs(
    ["Asistente", "Preguntas", "Contexto", "Avanzado"]
)

with tab_chat:
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown("### Input libre")
    st.caption("Comparti reglas de negocio, preferencias o aclaraciones en lenguaje natural.")
    chat_actions = st.columns([3, 1])
    with chat_actions[1]:
        if st.button("Limpiar chat", use_container_width=True):
            st.session_state["chat_history"] = []
            st.rerun()

    for msg in st.session_state["chat_history"]:
        _render_chat_bubble(msg["role"], str(msg["content"]))

    with st.form("chat_form", clear_on_submit=True):
        free_text = st.text_area(
            "Mensaje para Schema Agent",
            placeholder="Ej: Para negocio, 'year' significa anio de lanzamiento de pelicula.",
            height=90,
        )
        send_chat = st.form_submit_button("Enviar contexto extra", use_container_width=True)
        if send_chat and free_text.strip():
            clean = free_text.strip()
            st.session_state["chat_history"].append({"role": "user", "content": clean})
            with st.spinner("Enviando contexto extra..."):
                _submit_free_text_note(clean, data)
            if st.session_state.get("last_error"):
                st.session_state["chat_history"].append(
                    {"role": "assistant", "content": "No pude procesar el mensaje. Reintenta."}
                )
            else:
                latest = st.session_state.get("last") or {}
                new_status = str(latest.get("status", "-"))
                text = (
                    "Lo tome en cuenta y el contexto quedo listo."
                    if new_status == "ready"
                    else "Mensaje recibido. Todavia quedan ambiguedades por resolver."
                )
                st.session_state["chat_history"].append({"role": "assistant", "content": text})
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

with tab_questions:
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown("### Resolver ambiguedades")
    if not questions:
        st.success("No hay preguntas pendientes.")
    else:
        st.caption("Completa respuestas cortas y concretas. Todas se envian juntas.")
        with st.form("answers_form", clear_on_submit=False):
            answers: dict[str, Any] = {}
            missing_required = []
            for i, q in enumerate(questions, start=1):
                qid = str(q.get("id") or f"q{i}")
                label = str(q.get("question") or f"Pregunta {i}")
                default_value = str(existing_answers.get(qid) or "")
                value = st.text_area(
                    f"{i}. {label}",
                    value=default_value,
                    help=f"ID interno: {qid}",
                    key=f"answer_{qid}",
                    height=90,
                    placeholder="Escribi una respuesta clara.",
                ).strip()
                answers[qid] = value
                if not value:
                    missing_required.append(qid)

            submit = st.form_submit_button("Enviar respuestas", use_container_width=True)
            if submit:
                if missing_required:
                    st.error("Faltan respuestas para: " + ", ".join(missing_required))
                else:
                    with st.spinner("Enviando respuestas..."):
                        _safe_submit_answers(answers)
                    st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

with tab_context:
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown("### Contexto generado")
    if context_md:
        st.markdown(context_md)
    else:
        st.info("Todavia no hay contexto disponible.")
    st.markdown("</div>", unsafe_allow_html=True)

with tab_advanced:
    st.markdown("### Herramientas avanzadas")
    left_adv, right_adv = st.columns([1, 1], gap="large")
    with left_adv:
        with st.expander("Enviar JSON manual", expanded=False):
            raw_answers = st.text_area(
                "Pega JSON (objeto answers o {'answers': {...}})",
                value="{}",
                height=140,
            )
            if st.button("Enviar JSON", use_container_width=True):
                try:
                    parsed = json.loads(raw_answers)
                    payload_answers = (
                        parsed.get("answers")
                        if isinstance(parsed, dict) and "answers" in parsed
                        else parsed
                    )
                    if not isinstance(payload_answers, dict):
                        st.error("El JSON debe ser un objeto.")
                    else:
                        with st.spinner("Enviando JSON..."):
                            _safe_submit_answers(payload_answers)
                        st.rerun()
                except Exception as e:
                    st.error(f"JSON invalido: {e}")
    with right_adv:
        with st.expander("Preguntas detectadas (raw)", expanded=False):
            st.json(questions, expanded=False)
        with st.expander("Respuestas guardadas", expanded=False):
            st.json(existing_answers, expanded=False)

with st.expander("Salida tecnica", expanded=False):
    st.json(data, expanded=False)

