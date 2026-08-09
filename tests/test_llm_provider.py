import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app, process_review_job
from app.providers import LlmReviewProvider, ProviderError


AUTH_HEADERS = {"Authorization": "Bearer development-token"}
DIFF = "@@ -1 +1 @@\n+const value = input;\n"


def test_llm_job_without_an_api_key_fails_without_crashing() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/v1/reviews",
            headers=AUTH_HEADERS,
            json={"diff": DIFF, "options": {"provider": "llm"}},
        )
        status_response = client.get(
            f"/v1/reviews/{created.json()['jobId']}",
            headers=AUTH_HEADERS,
        )

    assert created.status_code == 202
    assert status_response.json()["status"] == "failed"
    assert "LLM_API_KEY is not configured" in status_response.json()["error"]


def test_invalid_provider_returns_invalid_provider_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/reviews",
            headers=AUTH_HEADERS,
            json={"diff": DIFF, "options": {"provider": "unsupported"}},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_provider"


def test_llm_provider_sends_diff_and_validates_structured_findings(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"findings":[{"id":"LLM-001:a.ts:1",'
                                '"ruleId":"LLM-001","path":"a.ts","line":1,'
                                '"severity":"high","category":"security",'
                                '"title":"SQL injection","evidence":"query"}]}'
                            )
                        }
                    }
                ]
            }

    def fake_post(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr("app.providers.httpx.post", fake_post)
    provider = LlmReviewProvider("test-key", "https://llm.example/v1/chat", "test-model")

    findings = provider.review_chunks([DIFF])

    assert findings[0].id == "LLM-001:a.ts:1"
    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer test-key"}  # type: ignore[index]
    assert DIFF in captured["kwargs"]["json"]["messages"][1]["content"]  # type: ignore[index]


def test_invalid_llm_finding_marks_the_job_failed(monkeypatch) -> None:
    class InvalidProvider:
        def review_chunks(self, _: list[str]):
            raise ProviderError("LLM provider finding has an invalid severity")

    monkeypatch.setattr(main_module, "create_review_provider", lambda *_: InvalidProvider())
    job: dict[str, object] = {"status": "queued"}

    asyncio.run(process_review_job(job, DIFF, 100, provider_name="llm"))

    assert job["status"] == "failed"
    assert "invalid severity" in job["error"]  # type: ignore[index]


def test_llm_provider_rejects_malformed_structured_output(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"findings":[{"line":"one"}]}'}}]}

    monkeypatch.setattr("app.providers.httpx.post", lambda *_, **__: FakeResponse())
    provider = LlmReviewProvider("test-key", "https://llm.example/v1/chat", "test-model")

    with pytest.raises(ProviderError, match="missing or invalid string fields"):
        provider.review_chunks([DIFF])
