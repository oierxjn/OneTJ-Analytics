import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings
from app.logging_utils import mask_sensitive_payload
from app.middleware import CollectorMiddleware
from app.schemas import ApiResponse, EventIn

logger = logging.getLogger("collector")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def build_error(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResponse(
            status="error",
            code=code,
            message=message,
            request_id=request_id,
        ).model_dump(),
    )


def request_id_from(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(CollectorMiddleware, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = request_id_from(request)
        return build_error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc.errors()[0]["msg"]), request_id)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = request_id_from(request)
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            405: "BAD_REQUEST",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            415: "UNSUPPORTED_MEDIA_TYPE",
            429: "RATE_LIMITED",
        }
        code = code_map.get(exc.status_code, "SERVER_ERROR")
        return build_error(exc.status_code, code, str(exc.detail), request_id)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, _: Exception) -> JSONResponse:
        request_id = request_id_from(request)
        return build_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "SERVER_ERROR", "internal server error", request_id)

    @app.post("/collector/v1/events", response_model=ApiResponse)
    async def collect_events(payload: EventIn, request: Request) -> Any:
        request_id = request_id_from(request)

        logger.info(
            "accepted event request_id=%s payload=%s",
            request_id,
            mask_sensitive_payload(payload.model_dump()),
        )
        return ApiResponse(status="ok", code="SUCCESS", message="accepted", request_id=request_id)

    return app


app = create_app()
