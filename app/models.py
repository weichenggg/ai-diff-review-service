from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    uptimeSeconds: float


class LimitsResponse(BaseModel):
    maxPayloadBytes: int
    chunkBytes: int
    maxConcurrentJobs: int
    rateLimitPerMinute: int


class SpecResponse(BaseModel):
    specVersion: str = "1.0"
    providers: list[str] = ["mock", "llm"]
    limits: LimitsResponse


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
