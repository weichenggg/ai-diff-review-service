from typing import Literal
from uuid import UUID

from pydantic import BaseModel


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
    diff: str
    options: ReviewOptions = ReviewOptions()


class CreateReviewResponse(BaseModel):
    jobId: UUID
    status: Literal["queued"] = "queued"


class ReviewStatusResponse(BaseModel):
    jobId: UUID
    status: Literal["queued", "running", "done", "failed"]
