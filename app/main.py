import asyncio
import signal
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.cache.store import CacheStore
from app.config import settings
from app.utils.errors import (
    DescriptorError,
    descriptor_error_handler,
    http_exception_handler,
    internal_error_handler,
    validation_error_handler,
)
from app.utils.logging import _SKIP_LOG_PATHS, request_id_middleware, setup_logging
from app.utils.rate_limit import get_real_ip

setup_logging()


limiter = Limiter(key_func=get_real_ip)

logger = structlog.get_logger()

_shutting_down = False
_in_flight = 0
_in_flight_lock: asyncio.Lock | None = None
_drain_event: asyncio.Event | None = None


def is_shutting_down() -> bool:
    return _shutting_down


async def _cache_cleanup_loop(cache: CacheStore):
    while True:
        await asyncio.sleep(settings.cache_cleanup_interval_seconds)
        try:
            await cache.cleanup_expired()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _shutting_down, _in_flight, _in_flight_lock, _drain_event
    _shutting_down = False
    _in_flight = 0
    _in_flight_lock = asyncio.Lock()
    _drain_event = asyncio.Event()
    _drain_event.set()

    settings.log_settings_summary()

    app.state.cache = CacheStore(settings.cache_db_path)
    await app.state.cache.init()
    cleanup_task = asyncio.create_task(_cache_cleanup_loop(app.state.cache))

    loop = asyncio.get_running_loop()

    def _handle_sigterm():
        global _shutting_down
        _shutting_down = True
        logger.info("graceful_shutdown_initiated", timeout=settings.shutdown_timeout)

    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
    except NotImplementedError:
        pass

    yield

    if _shutting_down:
        from app.utils.metrics import get_active_batch_count

        batch_timeout = settings.shutdown_batch_timeout
        poll_interval = 0.5
        elapsed = 0.0
        while get_active_batch_count() > 0 and elapsed < batch_timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        if get_active_batch_count() > 0:
            logger.warning("batch_drain_timeout", active_batches=get_active_batch_count())
        else:
            logger.info("all_batch_jobs_drained", elapsed_seconds=round(elapsed, 1))

        try:
            await asyncio.wait_for(_drain_event.wait(), timeout=settings.shutdown_timeout)
            logger.info("all_requests_drained")
        except TimeoutError:
            logger.warning("drain_timeout", remaining_requests=_in_flight)

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await app.state.cache.close()


try:
    _app_version = version("cognito-descriptor")
except PackageNotFoundError:
    _app_version = "unknown"

app = FastAPI(
    title="COGnito Image Descriptor",
    version=_app_version,
    description=(
        "위성영상 분석 API - 좌표 기반 역지오코딩, 토지피복 분류, "
        "Gemini AI 영상 설명, 맥락 정보를 통합 제공합니다."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "analysis",
            "description": "위성영상 분석 및 설명 생성 엔드포인트",
        },
        {
            "name": "data",
            "description": "개별 모듈 데이터 조회 (지오코딩, 토지피복, 맥락)",
        },
        {
            "name": "system",
            "description": "헬스체크 및 캐시 통계",
        },
    ],
)
app.state.limiter = limiter


async def _rate_limit_handler(request, exc):
    from app.utils.errors import _get_correlation_id

    import datetime as _dt

    retry_after_raw = getattr(exc, "retry_after", 60)
    if isinstance(retry_after_raw, _dt.datetime):
        delta = retry_after_raw - _dt.datetime.now(tz=retry_after_raw.tzinfo)
        retry_after = max(1, int(delta.total_seconds()))
    else:
        retry_after = int(retry_after_raw)
    return JSONResponse(
        status_code=429,
        content={
            "type": "https://problems.cognito-descriptor.io/rate-limit-exceeded",
            "title": "Rate Limit Exceeded",
            "status": 429,
            "detail": str(exc.detail) if hasattr(exc, "detail") else "요청 횟수 제한을 초과했습니다",
            "instance": _get_correlation_id(request),
        },
        headers={"Retry-After": str(retry_after)},
        media_type="application/problem+json",
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_exception_handler(DescriptorError, descriptor_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, internal_error_handler)


async def _timeout_error_handler(request, exc):
    from app.utils.errors import _get_correlation_id

    logger.warning("request_timeout", path=request.url.path, timeout=settings.request_timeout)
    return JSONResponse(
        status_code=504,
        content={
            "type": "https://problems.cognito-descriptor.io/gateway-timeout",
            "title": "Gateway Timeout",
            "status": 504,
            "detail": "요청 처리 시간이 초과되었습니다",
            "instance": _get_correlation_id(request),
        },
        media_type="application/problem+json",
    )


app.add_exception_handler(asyncio.TimeoutError, _timeout_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Correlation-ID", "X-Process-Time"],
)

app.add_middleware(GZipMiddleware, minimum_size=settings.gzip_min_size)


_SYSTEM_PATHS = _SKIP_LOG_PATHS


@app.middleware("http")
async def logging_middleware(request, call_next):
    return await request_id_middleware(request, call_next)


@app.middleware("http")
async def shutdown_middleware(request, call_next):
    global _in_flight, _in_flight_lock, _drain_event
    if _in_flight_lock is None:
        _in_flight_lock = asyncio.Lock()
        _drain_event = asyncio.Event()
        _drain_event.set()
    if _shutting_down and request.url.path not in _SYSTEM_PATHS:
        return JSONResponse(
            status_code=503,
            content={
                "type": "https://problems.cognito-descriptor.io/service-unavailable",
                "title": "Service Unavailable",
                "status": 503,
                "detail": "Server is shutting down",
            },
            media_type="application/problem+json",
        )
    async with _in_flight_lock:
        _in_flight += 1
        _drain_event.clear()
    try:
        response = await call_next(request)
        return response
    finally:
        async with _in_flight_lock:
            _in_flight -= 1
            if _in_flight == 0:
                _drain_event.set()


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(router, prefix="/api/v1")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
async def legacy_api_redirect(request: Request, path: str):
    """Redirect legacy /api/* requests to /api/v1/* for backward compatibility."""
    query_string = request.url.query
    new_url = f"/api/v1/{path}"
    if query_string:
        new_url = f"{new_url}?{query_string}"
    return RedirectResponse(url=new_url, status_code=307)


Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
