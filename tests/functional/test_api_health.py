from __future__ import annotations


def test_health_endpoint_returns_healthy(client) -> None:
    # Given / When
    resp = client.get("/health")
    # Then
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
