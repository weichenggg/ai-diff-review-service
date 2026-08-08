from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.mock_review_engine import Finding


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    uptimeSeconds: float


class LimitsResponse(BaseModel):
    maxPayloadBytes: int
    chunkBytes: int
    maxConcurrentJobs: int
    rateLimitPerMinute: int


class SpecResponse(BaseModel):
    specVersion: Literal["1.0"] = "1.0"
    providers: list[Literal["mock", "llm"]] = ["mock", "llm"]
    limits: LimitsResponse


class ReviewOptions(BaseModel):
    provider: Literal["mock", "llm"] = "mock"
    maxFindings: int = 100


class CreateReviewRequest(BaseModel):
    diff: str | None = None
    options: ReviewOptions = ReviewOptions()


class CreateReviewResponse(BaseModel):
    jobId: UUID
    status: Literal["queued"] = "queued"


class UsageResponse(BaseModel):
    inputBytes: int
    chunks: Literal[1] = 1
    cacheHit: bool = False


class ReviewStatusResponse(BaseModel):
    jobId: UUID
    status: Literal["queued", "running", "done", "failed"]
    findings: list[Finding] | None = None
    usage: UsageResponse | None = None
