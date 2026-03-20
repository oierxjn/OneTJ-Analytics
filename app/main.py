import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import Settings
from app.ingest import EventEnvelope, EventProducer, build_event_producer
from app.logging_utils import mask_sensitive_payload
from app.middleware import CollectorMiddleware, get_client_ip
from app.schemas import ApiResponse, EventIn
from app.updater_repository import UpdateManifestRepository
from app.updater_schemas import UpdateCheckQuery, UpdateCheckResponse
from app.updater_service import UpdateCheckService

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

# 格式化请求验证错误消息
def format_validation_message(exc: RequestValidationError | ValidationError) -> str:
    first_error = exc.errors()[0]
    loc = first_error.get("loc", ())
    msg = first_error.get("msg", "invalid request")
    field = None
    if len(loc) >= 2 and loc[0] in {"body", "query"} and isinstance(loc[1], str):
        field = loc[1]

    normalized_msg = str(msg).lower()
    if field:
        if normalized_msg == "field required":
            return f"missing required field: {field}"
        if "must not be empty" in normalized_msg:
            return f"field '{field}' must not be empty"
        if "must be a string" in normalized_msg:
            return f"field '{field}' must be a string"
        return f"field '{field}' {msg}"
    return str(msg)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        producer = build_event_producer(settings)
        update_manifest_repository = UpdateManifestRepository(settings.update_manifest_path)
        update_manifest_repository.load()
        app.state.event_producer = producer
        app.state.update_service = UpdateCheckService(update_manifest_repository)
        try:
            yield
        finally:
            await producer.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(CollectorMiddleware, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = request_id_from(request)
        return build_error(
            status.HTTP_400_BAD_REQUEST,
            "BAD_REQUEST",
            format_validation_message(exc),
            request_id,
        )

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
        event_producer: EventProducer = request.app.state.event_producer
        event = EventEnvelope.from_event(payload=payload, request_id=request_id, client_ip=get_client_ip(request))

        try:
            await event_producer.enqueue(event)
        except Exception as exc:
            logger.exception("failed to enqueue event request_id=%s error=%s", request_id, exc)
            raise HTTPException(status_code=500, detail="failed to enqueue event") from exc

        logger.info(
            "accepted event request_id=%s payload=%s",
            request_id,
            mask_sensitive_payload(payload.model_dump(exclude_none=True)),
        )
        return ApiResponse(status="ok", code="SUCCESS", message="accepted", request_id=request_id)

    @app.get("/updater/v1/check", response_model=UpdateCheckResponse, response_model_exclude_none=True)
    async def check_update(
        request: Request,
        platform: Literal["windows", "android"] = Query(...),
        arch: str | None = Query(default=None),
        current_version: str = Query(...),
        current_build: str = Query(...),
    ) -> UpdateCheckResponse:
        request_id = request_id_from(request)
        started_at = time.perf_counter()
        update_service: UpdateCheckService = request.app.state.update_service

        try:
            query = UpdateCheckQuery(
                platform=platform,
                arch=arch,
                current_version=current_version,
                current_build=current_build,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=format_validation_message(exc)) from exc

        try:
            data = update_service.check(query)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "update check request_id=%s platform=%s arch=%s current_version=%s current_build=%s has_update=%s latency_ms=%s",
            request_id,
            query.platform,
            query.arch or "",
            query.current_version,
            query.current_build,
            data.has_update,
            elapsed_ms,
        )
        return UpdateCheckResponse(
            status="ok",
            code="SUCCESS",
            message="accepted",
            request_id=request_id,
            data=data,
        )

    return app


app = create_app()
