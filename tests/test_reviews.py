from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app


AUTH_HEADERS = {"Authorization": "Bearer development-token"}


def test_v1_routes_require_a_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/reviews", json={"diff": "example"})

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Authentication is required"}
    }


def test_create_and_get_queued_review_job() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/v1/reviews",
            headers=AUTH_HEADERS,
            json={"diff": "example"},
        )
        job_id = created.json()["jobId"]
        fetched = client.get(f"/v1/reviews/{job_id}", headers=AUTH_HEADERS)

    assert created.status_code == 202
    assert UUID(job_id)
    assert created.json()["status"] == "queued"
    assert fetched.status_code == 200
    assert fetched.json() == {"jobId": job_id, "status": "queued"}


def test_unknown_review_job_returns_not_found() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/v1/reviews/00000000-0000-0000-0000-000000000000",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
