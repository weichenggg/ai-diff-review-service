import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from app.config import get_settings
from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.models import HealthResponse, LimitsResponse, SpecResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.started_at = time.monotonic()
    yield


app = FastAPI(title="AI Diff Review Service", lifespan=lifespan)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


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
