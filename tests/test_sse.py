import asyncio
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module
from app.main import (
    app,
    emit_job_event,
    initialize_job_events,
    process_review_job,
    stream_job_events,
)


AUTH_HEADERS = {"Authorization": "Bearer development-token"}


def review_diff() -> str:
    return """diff --git a/a.ts b/a.ts
--- a/a.ts
+++ b/a.ts
@@ -1 +1 @@
+eval(input);
"""


def parse_sse_events(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", maxsplit=1) for line in block.splitlines())
        events.append(
            {
                "id": int(fields["id"]),
                "event": fields["event"],
                "data": json.loads(fields["data"]),
            }
        )
    return events


def create_completed_job(client: TestClient) -> str:
    response = client.post(
        "/v1/reviews",
        headers=AUTH_HEADERS,
        json={"diff": review_diff()},
    )
    assert response.status_code == 202
    return response.json()["jobId"]


def test_completed_job_replays_full_event_history_in_order() -> None:
    with TestClient(app) as client:
        job_id = create_completed_job(client)
        response = client.get(f"/v1/reviews/{job_id}/events", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse_events(response.text)
    assert [event["event"] for event in events] == [
        "queued",
        "started",
        "finding",
        "completed",
    ]
    assert [event["id"] for event in events] == [1, 2, 3, 4]
    assert events[2]["data"]["id"] == "MOCK-001:a.ts:1"  # type: ignore[index]
    assert events[-1]["data"]["usage"]["cacheHit"] is False  # type: ignore[index]


def test_last_event_id_replays_only_later_events() -> None:
    with TestClient(app) as client:
        job_id = create_completed_job(client)
        response = client.get(
            f"/v1/reviews/{job_id}/events",
            headers={**AUTH_HEADERS, "Last-Event-ID": "2"},
        )

    events = parse_sse_events(response.text)
    assert [event["id"] for event in events] == [3, 4]
    assert [event["event"] for event in events] == ["finding", "completed"]


def test_live_subscription_receives_events_until_completion() -> None:
    async def receive_live_events() -> list[dict[str, object]]:
        job: dict[str, object] = {"status": "queued"}
        initialize_job_events(job)
        emit_job_event(job, "queued", {"status": "queued"})
        stream = stream_job_events(job, last_event_id=0)

        first_event = await anext(stream)
        processing = asyncio.create_task(process_review_job(job, review_diff(), 100))
        remaining_events = [event async for event in stream]
        await processing
        return parse_sse_events(first_event + "".join(remaining_events))

    events = asyncio.run(receive_live_events())

    assert [event["event"] for event in events] == [
        "queued",
        "started",
        "finding",
        "completed",
    ]


def test_failed_job_emits_failed_event_and_stream_terminates(monkeypatch) -> None:
    def fail(_: str, __: int) -> tuple[list[object], dict[str, object]]:
        raise RuntimeError("forced failure")

    monkeypatch.setattr(main_module, "compute_review_result", fail)

    async def receive_failed_events() -> list[dict[str, object]]:
        job: dict[str, object] = {"status": "queued"}
        initialize_job_events(job)
        emit_job_event(job, "queued", {"status": "queued"})
        await process_review_job(job, "diff", 100)
        return parse_sse_events("".join([event async for event in stream_job_events(job, 0)]))

    events = asyncio.run(receive_failed_events())

    assert [event["event"] for event in events] == ["queued", "started", "failed"]
    assert "forced failure" in events[-1]["data"]["error"]  # type: ignore[index]


def test_cached_job_has_its_own_replayable_event_history() -> None:
    with TestClient(app) as client:
        source_job_id = create_completed_job(client)
        cached = client.post(
            "/v1/reviews",
            headers=AUTH_HEADERS,
            json={"diff": review_diff()},
        )
        cached_job_id = cached.json()["jobId"]
        source_events = client.get(f"/v1/reviews/{source_job_id}/events", headers=AUTH_HEADERS)
        cached_events = client.get(f"/v1/reviews/{cached_job_id}/events", headers=AUTH_HEADERS)

    source_history = parse_sse_events(source_events.text)
    cached_history = parse_sse_events(cached_events.text)
    assert [event["event"] for event in cached_history] == [event["event"] for event in source_history]
    assert [event["id"] for event in cached_history] == list(range(1, len(cached_history) + 1))
    assert cached_history[-1]["data"]["usage"]["cacheHit"] is True  # type: ignore[index]


def test_unauthorized_event_stream_returns_401() -> None:
    with TestClient(app) as client:
        response = client.get(f"/v1/reviews/{uuid4()}/events")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
