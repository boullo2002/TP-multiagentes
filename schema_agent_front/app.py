from __future__ import annotations

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


st.set_page_config(page_title="Schema Agent Front", layout="wide")
st.title("Schema Agent Front (Streamlit)")
st.caption("Resolver ambigüedades del schema y mantener schema_context.json actualizado.")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("Refrescar estado", use_container_width=True):
        st.session_state["last"] = _get("/schema-agent/state")
with col2:
    if st.button("Regenerar contexto", use_container_width=True):
        st.session_state["last"] = _post("/schema-agent/run", {"force": True})

if "last" not in st.session_state:
    st.session_state["last"] = _get("/schema-agent/state")

data = st.session_state["last"]
status = data.get("status", "-")
schema_hash = data.get("schema_hash", "-")
st.markdown(f"**Estado:** `{status}`  |  **Schema hash:** `{schema_hash}`")

if status == "needs_human":
    st.warning("Hay ambigüedades. Completá respuestas y enviá.")
else:
    st.success("Contexto listo para Query Agent.")

questions = (data.get("draft") or {}).get("questions") or []
if questions:
    st.subheader("Preguntas ambiguas")
    st.json(questions, expanded=True)

st.subheader("Respuestas humanas")
default_answers = "{}"
answers_text = st.text_area(
    "Pegá JSON con answers (ej: {\"q1\":\"Año de lanzamiento\"})",
    value=default_answers,
    height=140,
)
if st.button("Enviar respuestas", use_container_width=True):
    try:
        import json

        parsed = json.loads(answers_text)
        answers = parsed.get("answers") if isinstance(parsed, dict) and "answers" in parsed else parsed
        if not isinstance(answers, dict):
            st.error("El JSON debe ser un objeto.")
        else:
            st.session_state["last"] = _post("/schema-agent/answer", {"answers": answers})
            st.rerun()
    except Exception as e:
        st.error(f"JSON inválido o error enviando respuestas: {e}")

st.subheader("Salida técnica")
st.json(data, expanded=False)

