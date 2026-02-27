import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.routes import router
from app.cache.store import CacheStore
from app.config import settings
from app.utils.errors import DescriptorError, descriptor_error_handler

_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(_log_level),
)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cache = CacheStore(settings.cache_db_path)
    await app.state.cache.init()
    yield
    await app.state.cache.close()


app = FastAPI(
    title="COGnito Image Descriptor",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(DescriptorError, descriptor_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
