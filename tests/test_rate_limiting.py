import json

from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings
from app.main import app


def request_body() -> bytes:
    return json.dumps({"diff": "@@ -1 +1 @@\n+console.log('x');"}).encode("utf-8")


def post_review(client: TestClient, token: str = "development-token"):
    return client.post(
        "/v1/reviews",
        content=request_body(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )


def test_first_thirty_posts_are_accepted_and_the_thirty_first_is_rate_limited() -> None:
    with TestClient(app) as client:
        responses = [post_review(client) for _ in range(30)]
        limited = post_review(client)

    assert [response.status_code for response in responses] == [202] * 30
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1


def test_different_authenticated_tokens_have_separate_rate_limits(monkeypatch) -> None:
    settings = Settings(api_token="token-one", api_tokens="token-two")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    with TestClient(app) as client:
        for _ in range(30):
            assert post_review(client, "token-one").status_code == 202
        limited = post_review(client, "token-one")
        second_token = post_review(client, "token-two")

    assert limited.status_code == 429
    assert second_token.status_code == 202


def test_get_requests_do_not_consume_the_post_rate_limit() -> None:
    with TestClient(app) as client:
        for _ in range(29):
            assert post_review(client).status_code == 202
        for _ in range(5):
            response = client.get(
                "/v1/reviews/00000000-0000-0000-0000-000000000000",
                headers={"Authorization": "Bearer development-token"},
            )
            assert response.status_code == 404
        thirtieth = post_review(client)
        limited = post_review(client)

    assert thirtieth.status_code == 202
    assert limited.status_code == 429


def test_rate_window_resets_after_one_minute(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(main_module.time, "monotonic", lambda: clock[0])

    with TestClient(app) as client:
        for _ in range(30):
            assert post_review(client).status_code == 202
        assert post_review(client).status_code == 429
        clock[0] += 60
        retried = post_review(client)

    assert retried.status_code == 202
