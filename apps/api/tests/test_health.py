from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_liveness_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"]
    assert body["environment"]


def test_versioned_readiness_reports_engine_version() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Proves the API is wired to packages/engine.
    assert body["engine_version"]


def test_openapi_schema_is_served() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"]
