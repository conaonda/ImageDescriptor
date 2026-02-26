from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.routes import router
from app.cache.store import CacheStore
from app.config import settings

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_level_from_name(settings.log_level)
    ),
)


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
app.include_router(router, prefix="/api")
