import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError

from app.config import get_settings
from app.diff_parser import parse_added_lines_by_file
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
    yield


app = FastAPI(
    title="AI Diff Review Service",
    lifespan=lifespan,
)

app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(
    RequestValidationError,
    validation_exception_handler,
)

bearer_scheme = HTTPBearer(auto_error=False)
v1_router = APIRouter(prefix="/v1")


async def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    if credentials is None or credentials.credentials != get_settings().api_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def process_review_job(
    job: dict[str, object],
    diff: str,
    max_findings: int,
) -> None:
    """Run deterministic mock review processing without letting failures escape."""
    try:
        job["status"] = "running"
        findings: list[Finding] = []
        for path, added_lines in parse_added_lines_by_file(diff).items():
            findings.extend(review_added_lines(path, added_lines))

        unique_findings = {finding.id: finding for finding in findings}
        ordered_findings = sorted(
            unique_findings.values(),
            key=lambda finding: (finding.path, finding.line, finding.ruleId),
        )
        job["findings"] = ordered_findings[:max_findings]
        job["usage"] = {
            "inputBytes": len(diff.encode("utf-8")),
            "chunks": 1,
            "cacheHit": False,
        }
        job["status"] = "done"
    except Exception:
        job["status"] = "failed"


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
    dependencies=[Depends(require_bearer_token)],
)
async def create_review(
    request: CreateReviewRequest,
    background_tasks: BackgroundTasks,
) -> CreateReviewResponse:
    job_id = uuid4()
    job: dict[str, object] = {"jobId": job_id, "status": "queued"}
    app.state.jobs[job_id] = job
    if request.options.provider == "mock":
        background_tasks.add_task(
            process_review_job,
            job,
            request.diff,
            request.options.maxFindings,
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
    return ReviewStatusResponse(**job)


app.include_router(v1_router)
