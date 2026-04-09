from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import get_app


def test_health_endpoint_returns_healthy() -> None:
    app = get_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
