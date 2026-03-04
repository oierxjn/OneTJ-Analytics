# OneTJ Analytics Backend (V1)

FastAPI-based data collector backend for OneTJ client integration tests.

## Features

- `POST /collector/v1/events` only.
- JSON request body validation for required string fields.
- Trim + non-empty validation for all required fields.
- Unified response contract with `status/code/message/request_id`.
- IP-based rate limiting (`16 req/min/IP` by default).
- Client IP resolution rule:
  - Prefer first IP from `X-Forwarded-For`.
  - Fallback to direct client IP.
- Masked logging for sensitive fields (`userid`, `username`).
- Optional HTTPS-only mode via env var.

## Local Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## Run (HTTP test mode)

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Run Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

## Example Request

```bash
curl -X POST "http://127.0.0.1:8000/collector/v1/events" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "Accept: application/json" \
  -d '{
    "userid":"2333333",
    "username":"张三",
    "client_version":"1.2.3+45",
    "device_brand":"HUAWEI",
    "device_model":"Pura 70",
    "dept_name":"计算机科学与技术学院",
    "school_name":"同济大学",
    "gender":"男",
    "platform":"ohos"
  }'
```

## Config

Copy `.env.example` to `.env` and adjust as needed.

- `REQUIRE_HTTPS=true`: reject non-HTTPS requests.
- `RATE_LIMIT_PER_MINUTE=16`: IP limit window threshold.
- `MAX_PAYLOAD_BYTES=1048576`: payload hard limit by `Content-Length`.
