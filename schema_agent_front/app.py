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


st.set_page_config(page_title="Schema Agent", layout="wide")
st.title("Schema Agent")
st.caption("Resolvé ambigüedades del schema en pasos simples.")

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

actions_col1, actions_col2, actions_col3 = st.columns([1, 1, 1])
with actions_col1:
    if st.button("Refrescar estado", use_container_width=True):
        with st.spinner("Refrescando estado..."):
            _safe_refresh()
        st.rerun()
with actions_col2:
    if st.button("Regenerar contexto", use_container_width=True):
        with st.spinner("Regenerando borrador..."):
            _safe_run(force=True)
        st.rerun()
with actions_col3:
    if st.button("Aprobar sin cambios", use_container_width=True):
        with st.spinner("Aprobando..."):
            _safe_run(force=True)
        st.rerun()

if st.session_state.get("last_error"):
    st.error(st.session_state["last_error"])

status_col1, status_col2, status_col3 = st.columns([1, 1, 2])
status_col1.metric("Estado", status)
status_col2.metric("Schema hash", schema_hash[:12] + "..." if len(schema_hash) > 15 else schema_hash)
status_col3.metric("Preguntas pendientes", str(len(questions)))

if status == "needs_human":
    st.warning("Hay ambigüedades. Completá las respuestas y enviá.")
else:
    st.success("Contexto listo para Query Agent.")

main_col, side_col = st.columns([2, 1], gap="large")

with main_col:
    st.subheader("Input libre (tipo chat)")
    st.caption("Podés dar contexto extra aunque no haya preguntas pendientes.")
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    free_text = st.chat_input("Ej: 'Para negocio, year se refiere al año de lanzamiento'")
    if free_text:
        clean = free_text.strip()
        st.session_state["chat_history"].append({"role": "user", "content": clean})
        with st.spinner("Enviando contexto extra..."):
            _submit_free_text_note(clean, data)
        if st.session_state.get("last_error"):
            st.session_state["chat_history"].append(
                {"role": "assistant", "content": "No pude procesar el mensaje. Revisá el error y reintentá."}
            )
        else:
            latest = st.session_state.get("last") or {}
            new_status = str(latest.get("status", "-"))
            st.session_state["chat_history"].append(
                {
                    "role": "assistant",
                    "content": (
                        "Recibido. Usé tu input para regenerar el contexto."
                        if new_status == "ready"
                        else "Recibido. Lo tomé como señal, pero todavía hay ambigüedades por resolver."
                    ),
                }
            )
        st.rerun()

    st.divider()
    st.subheader("Responder preguntas")
    if not questions:
        st.info("No hay preguntas pendientes. Podés regenerar contexto si querés revalidar.")
    else:
        with st.form("answers_form", clear_on_submit=False):
            answers: dict[str, Any] = {}
            missing_required = []
            for i, q in enumerate(questions, start=1):
                qid = str(q.get("id") or f"q{i}")
                label = str(q.get("question") or f"Pregunta {i}")
                help_text = qid
                default_value = ""
                existing_answers = data.get("context", {}).get("answers", {})
                if isinstance(existing_answers, dict) and qid in existing_answers:
                    default_value = str(existing_answers.get(qid) or "")
                value = st.text_area(
                    f"{i}. {label}",
                    value=default_value,
                    help=f"ID: {help_text}",
                    key=f"answer_{qid}",
                    height=90,
                ).strip()
                answers[qid] = value
                if not value:
                    missing_required.append(qid)

            submit = st.form_submit_button("Enviar respuestas", use_container_width=True)
            if submit:
                if missing_required:
                    st.error(
                        "Faltan respuestas para: "
                        + ", ".join(missing_required)
                        + ". Completalas o usá 'Aprobar sin cambios'."
                    )
                else:
                    with st.spinner("Enviando respuestas..."):
                        _safe_submit_answers(answers)
                    st.rerun()

    with st.expander("Modo avanzado: enviar JSON manual"):
        raw_answers = st.text_area(
            "Pegá JSON (objeto answers o {'answers': {...}})",
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
                st.error(f"JSON inválido: {e}")

with side_col:
    st.subheader("Borrador de contexto")
    if context_md:
        st.markdown(context_md)
    else:
        st.caption("Todavía no hay contexto generado.")

    with st.expander("Preguntas detectadas (raw)"):
        st.json(questions, expanded=False)

st.subheader("Salida técnica")
st.json(data, expanded=False)

