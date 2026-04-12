from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


def test_tp_agent_playground_reachable(client) -> None:
    # Given / When
    resp = client.get("/tp-agent/playground/")
    # Then
    assert resp.status_code == 200


def test_tp_agent_invoke_returns_runnable_output(monkeypatch) -> None:
    # Given: Runnable mínimo (LangServe exige Runnable, no MagicMock)
    from api.main import get_app

    out_msg = AIMessage(content="respuesta de prueba invoke")

    def _fake_graph(state: dict, config=None) -> dict:
        return {
            **state,
            "messages": list(state.get("messages", [])) + [out_msg],
            "mode": "query",
        }

    stub = RunnableLambda(_fake_graph)
    monkeypatch.setattr("api.main.get_compiled_graph", lambda: stub)

    client = TestClient(get_app())
    # When
    resp = client.post(
        "/tp-agent/invoke",
        json={
            "input": {
                "messages": [{"type": "human", "content": "cuántos clientes hay en total"}],
                "session_id": "test-invoke",
            }
        },
    )
    # Then
    assert resp.status_code == 200
    data = resp.json()
    assert "output" in data
    assert data["output"].get("mode") == "query"
