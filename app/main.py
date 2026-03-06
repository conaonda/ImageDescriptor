import asyncio
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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


async def _cache_cleanup_loop(cache: CacheStore):
    while True:
        await asyncio.sleep(CACHE_CLEANUP_INTERVAL_SECONDS)
        try:
            await cache.cleanup_expired()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cache = CacheStore(settings.cache_db_path)
    await app.state.cache.init()
    cleanup_task = asyncio.create_task(_cache_cleanup_loop(app.state.cache))
    yield
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def logging_middleware(request, call_next):
    return await request_id_middleware(request, call_next)


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
