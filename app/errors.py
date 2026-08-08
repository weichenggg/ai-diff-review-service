from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
    return error_response(500, "internal", "An internal error occurred")


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code == 401:
        return error_response(401, "unauthorized", "Authentication is required")

    if exc.status_code == 404:
        return error_response(404, "not_found", "The requested resource was not found")

    if exc.status_code == 409:
        message = exc.detail if isinstance(exc.detail, str) else "Idempotency key conflict"
        return error_response(409, "idempotency_conflict", message)

    if exc.status_code == 413:
        message = exc.detail if isinstance(exc.detail, str) else "Payload too large"
        return error_response(413, "payload_too_large", message)

    if exc.status_code == 422:
        message = exc.detail if isinstance(exc.detail, str) else "Invalid unified diff"
        return error_response(422, "invalid_diff", message)

    if exc.status_code == 429:
        message = exc.detail if isinstance(exc.detail, str) else "Rate limit exceeded"
        return error_response(429, "rate_limited", message, headers=exc.headers)

    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return error_response(exc.status_code, "internal", message)


async def validation_exception_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return error_response(400, "invalid_json", "The request body is invalid")
