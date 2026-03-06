import asyncio
import signal
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import router
from app.cache.store import CacheStore
from app.config import settings
from app.utils.errors import DescriptorError, descriptor_error_handler
from app.utils.logging import request_id_middleware, setup_logging
from app.utils.rate_limit import get_real_ip

setup_logging()

CACHE_CLEANUP_INTERVAL_SECONDS = 3600

limiter = Limiter(key_func=get_real_ip)

logger = structlog.get_logger()

_shutting_down = False
_in_flight = 0
_in_flight_lock = asyncio.Lock()
_drain_event = asyncio.Event()
_drain_event.set()


def is_shutting_down() -> bool:
    return _shutting_down


async def _cache_cleanup_loop(cache: CacheStore):
    while True:
        await asyncio.sleep(CACHE_CLEANUP_INTERVAL_SECONDS)
        try:
            await cache.cleanup_expired()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _shutting_down, _in_flight
    _shutting_down = False
    _in_flight = 0
    _drain_event.set()

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
        try:
            await asyncio.wait_for(_drain_event.wait(), timeout=settings.shutdown_timeout)
            logger.info("all_requests_drained")
        except asyncio.TimeoutError:
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(DescriptorError, descriptor_error_handler)


async def _timeout_error_handler(request, exc):
    logger.warning("request_timeout", path=request.url.path, timeout=settings.request_timeout)
    return JSONResponse(status_code=504, content={"detail": "Gateway Timeout"})


app.add_exception_handler(asyncio.TimeoutError, _timeout_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


_SYSTEM_PATHS = {"/health", "/metrics", "/api/health", "/api/cache/stats"}


@app.middleware("http")
async def logging_middleware(request, call_next):
    return await request_id_middleware(request, call_next)



@app.middleware("http")
async def shutdown_middleware(request, call_next):
    global _in_flight
    if _shutting_down:
        return JSONResponse(
            status_code=503,
            content={"detail": "Server is shutting down"},
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


app.include_router(router, prefix="/api")

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
