import asyncio
from uuid import UUID

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app, create_review, process_review_job
from app.models import CreateReviewRequest, ReviewOptions


AUTH_HEADERS = {"Authorization": "Bearer development-token"}


def test_v1_routes_require_a_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/reviews", json={"diff": "example"})

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Authentication is required"}
    }


def test_job_lifecycle_is_queued_before_background_processing_then_done() -> None:
    with TestClient(app):
        tasks = BackgroundTasks()
        response = asyncio.run(
            create_review(
                CreateReviewRequest(diff="@@ -1 +1 @@\n+console.log('x');"),
                tasks,
            )
        )
        job = app.state.jobs[response.jobId]

        assert response.model_dump(mode="json") == {
            "jobId": str(response.jobId),
            "status": "queued",
        }
        assert job["status"] == "queued"

        asyncio.run(tasks())

        assert job["status"] == "done"


def test_processor_transitions_to_running_before_it_parses(monkeypatch) -> None:
    job: dict[str, object] = {"status": "queued"}

    def observe_running_state(_: str) -> dict[str, list[object]]:
        assert job["status"] == "running"
        return {}

    monkeypatch.setattr(main_module, "parse_added_lines_by_file", observe_running_state)

    asyncio.run(process_review_job(job, "diff", max_findings=100))

    assert job["status"] == "done"


def test_post_returns_queued_and_get_returns_exact_completed_findings() -> None:
    diff = """diff --git a/src/example.ts b/src/example.ts
--- a/src/example.ts
+++ b/src/example.ts
@@ -40 +40 @@
+console.log(eval(input)); // TODO
"""
    with TestClient(app) as client:
        created = client.post("/v1/reviews", headers=AUTH_HEADERS, json={"diff": diff})
        job_id = created.json()["jobId"]
        fetched = client.get(f"/v1/reviews/{job_id}", headers=AUTH_HEADERS)

    assert created.status_code == 202
    assert created.json() == {"jobId": job_id, "status": "queued"}
    assert UUID(job_id)
    assert fetched.status_code == 200
    assert fetched.json() == {
        "jobId": job_id,
        "status": "done",
        "findings": [
            {
                "id": "MOCK-001:src/example.ts:40",
                "ruleId": "MOCK-001",
                "path": "src/example.ts",
                "line": 40,
                "severity": "critical",
                "category": "security",
                "title": "eval usage",
                "evidence": "console.log(eval(input)); // TODO",
            },
            {
                "id": "MOCK-007:src/example.ts:40",
                "ruleId": "MOCK-007",
                "path": "src/example.ts",
                "line": 40,
                "severity": "low",
                "category": "style",
                "title": "console.log left in",
                "evidence": "console.log(eval(input)); // TODO",
            },
            {
                "id": "MOCK-008:src/example.ts:40",
                "ruleId": "MOCK-008",
                "path": "src/example.ts",
                "line": 40,
                "severity": "low",
                "category": "style",
                "title": "unresolved marker",
                "evidence": "console.log(eval(input)); // TODO",
            },
        ],
        "usage": {"inputBytes": len(diff.encode("utf-8")), "chunks": 1, "cacheHit": False},
    }


def test_multiple_files_are_sorted_by_path_then_line_then_rule_id() -> None:
    diff = """diff --git a/z.ts b/z.ts
--- a/z.ts
+++ b/z.ts
@@ -1 +9 @@
+console.log('z');
diff --git a/a.ts b/a.ts
--- a/a.ts
+++ b/a.ts
@@ -1 +7 @@
+// TODO
@@ -2 +3 @@
+eval(input);
"""
    job: dict[str, object] = {"status": "queued"}

    asyncio.run(process_review_job(job, diff, max_findings=100))

    assert [finding.id for finding in job["findings"]] == [  # type: ignore[index]
        "MOCK-001:a.ts:3",
        "MOCK-008:a.ts:7",
        "MOCK-007:z.ts:9",
    ]


def test_duplicate_findings_are_removed_before_storage() -> None:
    diff = """diff --git a/a.ts b/a.ts
--- a/a.ts
+++ b/a.ts
@@ -1 +5 @@
+eval(input);
@@ -1 +5 @@
+eval(input);
"""
    job: dict[str, object] = {"status": "queued"}

    asyncio.run(process_review_job(job, diff, max_findings=100))

    assert [finding.id for finding in job["findings"]] == ["MOCK-001:a.ts:5"]  # type: ignore[index]


def test_max_findings_truncates_the_complete_ordered_list() -> None:
    diff = """diff --git a/a.ts b/a.ts
--- a/a.ts
+++ b/a.ts
@@ -1 +1 @@
+console.log(eval(input));
"""
    job: dict[str, object] = {"status": "queued"}

    asyncio.run(process_review_job(job, diff, max_findings=1))

    assert [finding.id for finding in job["findings"]] == ["MOCK-001:a.ts:1"]  # type: ignore[index]


def test_usage_input_bytes_is_the_utf8_encoded_diff_length() -> None:
    diff = """diff --git a/a.ts b/a.ts
--- a/a.ts
+++ b/a.ts
@@ -1 +1 @@
+// TODO: café
"""
    job: dict[str, object] = {"status": "queued"}

    asyncio.run(process_review_job(job, diff, max_findings=100))

    assert job["usage"] == {
        "inputBytes": len(diff.encode("utf-8")),
        "chunks": 1,
        "cacheHit": False,
    }


def test_processing_failure_marks_the_job_as_failed(monkeypatch) -> None:
    def raise_unexpected_error(_: str) -> dict[str, list[object]]:
        raise RuntimeError("forced parser failure")

    monkeypatch.setattr(main_module, "parse_added_lines_by_file", raise_unexpected_error)
    job: dict[str, object] = {"status": "queued"}

    asyncio.run(process_review_job(job, "diff", max_findings=100))

    assert job["status"] == "failed"


def test_unknown_review_job_returns_not_found() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/v1/reviews/00000000-0000-0000-0000-000000000000",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
