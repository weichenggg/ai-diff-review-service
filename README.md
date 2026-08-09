# AI Diff Review Service

Initial FastAPI foundation for the take-home assignment. This stage exposes only the public health and specification endpoints.

## Requirements

- Python 3.11 or newer

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Optionally create a `.env` file to override the public metadata and declared limits:

```env
VERSION=0.1.0
MAX_PAYLOAD_BYTES=1048576
CHUNK_BYTES=65536
MAX_CONCURRENT_JOBS=4
RATE_LIMIT_PER_MINUTE=30
API_TOKEN=development-token
LLM_API_KEY=
LLM_API_URL=https://api.openai.com/v1/chat/completions
LLM_MODEL=gpt-4.1-mini
```

Run the service:

```powershell
uvicorn app.main:app --reload
```

The service is available at `http://127.0.0.1:8000`.

## Public endpoints

- `GET /health` returns service status, semantic version, and uptime in seconds.
- `GET /spec` returns spec version, advertised providers, and the configured limits.

## Tests

```powershell
pytest
```

Authentication and review-processing endpoints are intentionally not included in this foundation step.

## Day 2 review endpoints

All `/v1/*` endpoints require `Authorization: Bearer <API_TOKEN>`. The default
local token is `development-token` and may be overridden with `API_TOKEN`.

- `POST /v1/reviews` creates an in-memory queued review job and returns `202`.
- `GET /v1/reviews/{jobId}` returns the stored job status.

Jobs are deliberately only queued at this stage; processing is not yet implemented.
