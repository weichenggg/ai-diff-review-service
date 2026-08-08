import asyncio
import threading

from app import main as main_module
from app.main import process_review_job


def test_four_jobs_overlap_and_a_fifth_waits_for_a_slot(monkeypatch) -> None:
    started_four = threading.Event()
    release_work = threading.Event()
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def blocking_compute(_: str, __: int) -> tuple[list[object], dict[str, object]]:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 4:
                started_four.set()
        release_work.wait(timeout=2)
        with state_lock:
            active -= 1
        return [], {"inputBytes": 0, "chunks": 1, "cacheHit": False}

    monkeypatch.setattr(main_module, "compute_review_result", blocking_compute)

    async def run_jobs() -> list[dict[str, object]]:
        semaphore = asyncio.Semaphore(4)
        jobs: list[dict[str, object]] = [{"status": "queued"} for _ in range(5)]
        tasks = [
            asyncio.create_task(process_review_job(job, "diff", 100, semaphore))
            for job in jobs
        ]

        assert await asyncio.to_thread(started_four.wait, 1)
        assert [job["status"] for job in jobs[:4]] == ["running"] * 4
        assert jobs[4]["status"] == "queued"
        assert maximum_active == 4

        release_work.set()
        await asyncio.gather(*tasks)
        return jobs

    jobs = asyncio.run(run_jobs())

    assert maximum_active == 4
    assert [job["status"] for job in jobs] == ["done"] * 5


def test_failure_releases_the_semaphore_slot_for_the_next_job(monkeypatch) -> None:
    calls = 0
    calls_lock = threading.Lock()

    def fail_once(_: str, __: int) -> tuple[list[object], dict[str, object]]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            raise RuntimeError("expected test failure")
        return [], {"inputBytes": 0, "chunks": 1, "cacheHit": False}

    monkeypatch.setattr(main_module, "compute_review_result", fail_once)

    async def run_jobs() -> tuple[dict[str, object], dict[str, object]]:
        semaphore = asyncio.Semaphore(1)
        failed_job: dict[str, object] = {"status": "queued"}
        completed_job: dict[str, object] = {"status": "queued"}
        await asyncio.gather(
            process_review_job(failed_job, "first", 100, semaphore),
            process_review_job(completed_job, "second", 100, semaphore),
        )
        return failed_job, completed_job

    failed_job, completed_job = asyncio.run(run_jobs())

    assert calls == 2
    assert failed_job["status"] == "failed"
    assert completed_job["status"] == "done"
