from __future__ import annotations

from fastapi.testclient import TestClient

import api.main as api_main
from api.main import get_app


def test_openai_chat_completions_shape(monkeypatch) -> None:
    def _stub_run(_query: str) -> str:
        return "Respuesta de prueba (sin LLM)."

    monkeypatch.setattr(api_main, "_run_graph_for_query", _stub_run)

    app = get_app()
    client = TestClient(app)
    payload = {
        "model": "tp-multiagentes",
        "messages": [{"role": "user", "content": "Hola"}],
        "stream": False,
    }
    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data
    assert data["choices"][0]["message"]["role"] == "assistant"
