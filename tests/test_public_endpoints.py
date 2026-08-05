from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_contract_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert isinstance(body["uptimeSeconds"], (int, float))
    assert body["uptimeSeconds"] >= 0


def test_spec_returns_contract_defaults() -> None:
    with TestClient(app) as client:
        response = client.get("/spec")

    assert response.status_code == 200
    assert response.json() == {
        "specVersion": "1.0",
        "providers": ["mock", "llm"],
        "limits": {
            "maxPayloadBytes": 1_048_576,
            "chunkBytes": 65_536,
            "maxConcurrentJobs": 4,
            "rateLimitPerMinute": 30,
        },
    }
