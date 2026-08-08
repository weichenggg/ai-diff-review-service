import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


AUTH_HEADERS = {
    "Authorization": "Bearer development-token",
    "Content-Type": "application/json",
}


def test_payload_over_one_mebibyte_returns_payload_too_large() -> None:
    oversized_body = json.dumps({"diff": "x" * 1_048_576}).encode("utf-8")

    with TestClient(app) as client:
        response = client.post("/v1/reviews", content=oversized_body, headers=AUTH_HEADERS)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_malformed_json_returns_invalid_json() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/reviews", content=b'{"diff":', headers=AUTH_HEADERS)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"diff": ""},
        {"diff": "this is not a unified diff"},
    ],
)
def test_missing_empty_or_unparseable_diff_returns_invalid_diff(body: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post("/v1/reviews", json=body, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_diff"


def test_old_events_endpoint_is_not_public_api_any_more() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/v1/reviews/00000000-0000-0000-0000-000000000000/events",
            headers={"Authorization": "Bearer development-token"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
