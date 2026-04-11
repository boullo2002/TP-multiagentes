from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

import api.openai_graph as openai_graph
from api.main import get_app


def test_openai_chat_completions_shape(monkeypatch) -> None:
    def _stub_invoke(_msgs) -> str:
        return "Respuesta de prueba (sin LLM)."

    monkeypatch.setattr(openai_graph, "invoke_graph_for_chat_request", _stub_invoke)

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


def test_openai_chat_completions_stream_sse(monkeypatch) -> None:
    def _stub_invoke(_msgs) -> str:
        return "Hola streaming"

    monkeypatch.setattr(openai_graph, "invoke_graph_for_chat_request", _stub_invoke)

    app = get_app()
    client = TestClient(app)
    payload = {
        "model": "tp-multiagentes",
        "messages": [{"role": "user", "content": "Hola"}],
        "stream": True,
    }
    with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in (resp.headers.get("content-type") or "")
        raw = "".join(resp.iter_text())
    assert "chat.completion.chunk" in raw
    assert "Hola streaming" in raw
    assert "data: [DONE]" in raw
    assert "stop" in raw


def test_openai_chat_completions_mcp_unavailable_503(monkeypatch) -> None:
    def _fail(_msgs) -> str:
        raise httpx.ConnectError("connection refused", request=None)

    monkeypatch.setattr(openai_graph, "invoke_graph_for_chat_request", _fail)

    app = get_app()
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "tp-multiagentes",
            "messages": [{"role": "user", "content": "Hola"}],
            "stream": False,
        },
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "mcp_unavailable"


def test_openai_models_endpoint_returns_configured_model() -> None:
    app = get_app()
    client = TestClient(app)
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    ids = {m["id"] for m in data["data"]}
    assert "tp-multiagentes" in ids
