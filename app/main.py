import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import router
from app.cache.store import CacheStore
from app.config import settings
from app.utils.errors import DescriptorError, descriptor_error_handler
from app.utils.rate_limit import get_real_ip

_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(_log_level),
)

limiter = Limiter(key_func=get_real_ip)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cache = CacheStore(settings.cache_db_path)
    await app.state.cache.init()
    yield
    await app.state.cache.close()


app = FastAPI(
    title="COGnito Image Descriptor",
    version="0.3.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(DescriptorError, descriptor_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(router, prefix="/api")
