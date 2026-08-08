import asyncio
import copy
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from hashlib import sha256
from math import ceil
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.chunking import chunk_unified_diff
from app.config import get_settings
from app.diff_parser import HUNK_HEADER_PATTERN, parse_added_lines_by_file
from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.mock_review_engine import Finding, review_added_lines
from app.models import (
    HealthResponse,
    CreateReviewRequest,
    CreateReviewResponse,
    LimitsResponse,
    ReviewStatusResponse,
    SpecResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.started_at = time.monotonic()
    app.state.jobs = {}
    app.state.result_cache = {}
    app.state.idempotency_keys = {}
    app.state.review_semaphore = asyncio.Semaphore(get_settings().max_concurrent_jobs)
    app.state.rate_limit_requests = {}
    yield


app = FastAPI(
    title="AI Diff Review Service",
    lifespan=lifespan,
)

app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(
    RequestValidationError,
    validation_exception_handler,
)

bearer_scheme = HTTPBearer(auto_error=False)
v1_router = APIRouter(prefix="/v1")


async def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.credentials not in get_settings().valid_api_tokens:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.credentials


async def enforce_review_rate_limit(
    request: Request,
    bearer_token: str = Depends(require_bearer_token),
) -> None:
    """Apply a per-token sliding-window limit to review submissions only."""
    if len(await request.body()) > get_settings().max_payload_bytes:
        raise HTTPException(status_code=413, detail="Request body exceeds the maximum payload size")

    now = time.monotonic()
    window_start = now - 60
    request_times: deque[float] = app.state.rate_limit_requests.setdefault(
        bearer_token,
        deque(),
    )
    while request_times and request_times[0] <= window_start:
        request_times.popleft()

    if len(request_times) >= get_settings().rate_limit_per_minute:
        retry_after = max(1, ceil(request_times[0] + 60 - now))
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded; retry after the indicated delay",
            headers={"Retry-After": str(retry_after)},
        )

    request_times.append(now)


def initialize_job_events(job: dict[str, object]) -> None:
    """Attach the in-memory event log and notifier used by SSE subscribers."""
    job.setdefault("events", [])
    job.setdefault("eventSignal", asyncio.Event())
    job.setdefault("cacheAliases", [])


def _append_job_event(job: dict[str, object], event_type: str, data: dict[str, object]) -> None:
    initialize_job_events(job)
    events: list[dict[str, object]] = job["events"]  # type: ignore[assignment]
    events.append({"id": len(events) + 1, "event": event_type, "data": data})
    event_signal: asyncio.Event = job["eventSignal"]  # type: ignore[assignment]
    event_signal.set()


def emit_job_event(job: dict[str, object], event_type: str, data: dict[str, object]) -> None:
    """Store an event and fan it out to cached jobs that reuse this job's result."""
    _append_job_event(job, event_type, data)

    cache_aliases: list[UUID] = job["cacheAliases"]  # type: ignore[assignment]
    for alias_job_id in cache_aliases:
        alias_job = app.state.jobs.get(alias_job_id)
        if alias_job is None:
            continue
        alias_data = copy.deepcopy(data)
        if event_type == "done":
            usage = dict(alias_data["usage"])
            usage["cacheHit"] = True
            alias_data["usage"] = usage
        _append_job_event(alias_job, event_type, alias_data)


def copy_source_events_to_cached_job(source_job: dict[str, object], cached_job: dict[str, object]) -> None:
    """Replay existing source events into a newly-created cached job's own log."""
    source_events: list[dict[str, object]] = source_job.get("events", [])  # type: ignore[assignment]
    for event in source_events:
        data = copy.deepcopy(event["data"])
        if event["event"] == "done":
            usage = dict(data["usage"])
            usage["cacheHit"] = True
            data["usage"] = usage
        _append_job_event(cached_job, event["event"], data)


def format_sse_event(event: dict[str, object]) -> str:
    return (
        f"id: {event['id']}\n"
        f"event: {event['event']}\n"
        f"data: {json.dumps(event['data'], separators=(',', ':'))}\n\n"
    )


async def stream_job_events(job: dict[str, object], last_event_id: int) -> object:
    """Replay stored events and wait for live ones until a terminal event is sent."""
    next_event_id = last_event_id + 1
    while True:
        initialize_job_events(job)
        events: list[dict[str, object]] = job["events"]  # type: ignore[assignment]
        for event in events:
            if event["id"] < next_event_id:
                continue
            next_event_id = event["id"] + 1
            yield format_sse_event(event)
            if event["event"] == "done" or event["data"].get("status") == "failed":
                return

        event_signal: asyncio.Event = job["eventSignal"]  # type: ignore[assignment]
        event_signal.clear()
        if len(events) >= next_event_id:
            continue
        if events and (
            events[-1]["event"] == "done"
            or events[-1]["data"].get("status") == "failed"
        ):
            return
        await event_signal.wait()


def compute_review_result(diff: str, max_findings: int) -> tuple[list[Finding], dict[str, object]]:
    """Run the CPU-bound parse and mock-review work for one job."""
    findings: list[Finding] = []
    chunks = chunk_unified_diff(diff)
    for chunk in chunks:
        for path, added_lines in parse_added_lines_by_file(chunk).items():
            findings.extend(review_added_lines(path, added_lines))

    unique_findings = {finding.id: finding for finding in findings}
    ordered_findings = sorted(
        unique_findings.values(),
        key=lambda finding: (finding.path, finding.line, finding.ruleId),
    )
    return ordered_findings[:max_findings], {
        "inputBytes": len(diff.encode("utf-8")),
        "chunks": len(chunks),
        "cacheHit": False,
    }


async def process_review_job(
    job: dict[str, object],
    diff: str,
    max_findings: int,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    """Process one job once a review-processing slot is available."""
    active_semaphore = semaphore or asyncio.Semaphore(1)
    async with active_semaphore:
        job["status"] = "running"
        emit_job_event(job, "status", {"status": "running"})
        try:
            findings, usage = await asyncio.to_thread(compute_review_result, diff, max_findings)
            job["findings"] = findings
            job["usage"] = usage
            job["status"] = "done"
            for finding in findings:
                emit_job_event(job, "finding", asdict(finding))
            emit_job_event(
                job,
                "done",
                {"total": len(findings), "usage": usage},
            )
        except Exception as exc:
            job["status"] = "failed"
            error = f"Processing failed: {exc}"
            job["error"] = error
            emit_job_event(job, "status", {"status": "failed", "error": error})


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()

    return HealthResponse(
        version=settings.version,
        uptimeSeconds=time.monotonic() - app.state.started_at,
    )


@app.get("/spec", response_model=SpecResponse)
async def spec() -> SpecResponse:
    settings = get_settings()

    return SpecResponse(
        limits=LimitsResponse(
            maxPayloadBytes=settings.max_payload_bytes,
            chunkBytes=settings.chunk_bytes,
            maxConcurrentJobs=settings.max_concurrent_jobs,
            rateLimitPerMinute=settings.rate_limit_per_minute,
        )
    )


@v1_router.post(
    "/reviews",
    response_model=CreateReviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_review_rate_limit)],
)
async def create_review(
    http_request: Request,
    request: CreateReviewRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CreateReviewResponse:
    body_hash = sha256(await http_request.body()).hexdigest()

    if request.diff is None or not request.diff.strip() or not any(
        HUNK_HEADER_PATTERN.match(line) for line in request.diff.splitlines()
    ):
        raise HTTPException(status_code=422, detail="diff must be a parseable unified diff")

    if idempotency_key is not None:
        prior_request = app.state.idempotency_keys.get(idempotency_key)
        if prior_request is not None:
            if prior_request["bodyHash"] != body_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with a different request body",
                )
            return CreateReviewResponse(jobId=prior_request["jobId"])

    job_id = uuid4()
    cached_job_id = app.state.result_cache.get(body_hash)
    job: dict[str, object] = {"jobId": job_id, "status": "queued"}
    initialize_job_events(job)

    if cached_job_id is not None:
        job["cacheSourceJobId"] = cached_job_id

    app.state.jobs[job_id] = job
    if idempotency_key is not None:
        app.state.idempotency_keys[idempotency_key] = {
            "bodyHash": body_hash,
            "jobId": job_id,
        }

    if cached_job_id is None:
        app.state.result_cache[body_hash] = job_id
        emit_job_event(job, "status", {"status": "queued"})
    else:
        source_job = app.state.jobs[cached_job_id]
        initialize_job_events(source_job)
        source_job["cacheAliases"].append(job_id)  # type: ignore[index]
        copy_source_events_to_cached_job(source_job, job)

    if cached_job_id is None and request.options.provider == "mock":
        background_tasks.add_task(
            process_review_job,
            job,
            request.diff,
            request.options.maxFindings,
            app.state.review_semaphore,
        )
    return CreateReviewResponse(jobId=job_id)


@v1_router.get(
    "/reviews/{job_id}",
    response_model=ReviewStatusResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(require_bearer_token)],
)
async def get_review(job_id: UUID) -> ReviewStatusResponse:
    job = app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="The requested resource was not found")

    source_job_id = job.get("cacheSourceJobId")
    if source_job_id is not None:
        source_job = app.state.jobs.get(source_job_id)
        if source_job is not None:
            response: dict[str, object] = {
                "jobId": job_id,
                "status": source_job["status"],
            }
            if source_job["status"] == "done":
                usage = dict(source_job["usage"])
                usage["cacheHit"] = True
                response["findings"] = source_job["findings"]
                response["usage"] = usage
            return ReviewStatusResponse(**response)

    return ReviewStatusResponse(**job)


@v1_router.get(
    "/reviews/{job_id}/stream",
    dependencies=[Depends(require_bearer_token)],
)
async def review_stream(
    job_id: UUID,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    job = app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="The requested resource was not found")

    try:
        replay_after = int(last_event_id) if last_event_id is not None else 0
    except ValueError:
        replay_after = 0
    return StreamingResponse(
        stream_job_events(job, replay_after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


app.include_router(v1_router)
