import time
import uuid
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import Settings

# 获取客户端IP地址
#
# 优先从请求头中获取 "x-forwarded-for" 字段，该字段包含客户端的真实IP地址
# 如果不存在该字段，则返回请求的客户端主机地址
# 如果请求中没有客户端信息，则返回 "unknown"
def get_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def error_response(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "code": code,
            "message": message,
            "request_id": request_id,
        },
    )


class CollectorMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.lock = Lock()
        self.window_by_ip: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        if request.url.path == "/collector/v1/events" and request.method == "POST":
            content_type = request.headers.get("content-type", "").lower()
            if not content_type.startswith("application/json"):
                return error_response(
                    415,
                    "UNSUPPORTED_MEDIA_TYPE",
                    "content-type must be application/json",
                    request_id,
                )

        if self.settings.require_https and request.url.scheme != "https":
            return error_response(400, "BAD_REQUEST", "https required", request_id)

        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.settings.max_payload_bytes:
            return error_response(413, "PAYLOAD_TOO_LARGE", "payload too large", request_id)

        ip = get_client_ip(request)
        if not self._allow_request(ip):
            return error_response(429, "RATE_LIMITED", "rate limit exceeded", request_id)

        response = await call_next(request)
        return response

    def _allow_request(self, ip: str) -> bool:
        now = time.time()
        lower_bound = now - 60
        with self.lock:
            request_window = self.window_by_ip[ip]
            while request_window and request_window[0] <= lower_bound:
                request_window.popleft()

            if len(request_window) >= self.settings.rate_limit_per_minute:
                return False

            request_window.append(now)
            return True
