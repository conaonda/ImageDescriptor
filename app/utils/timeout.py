import asyncio

from app.config import settings


async def apply_timeout(coro, request=None):
    path = request.url.path if request else ""
    excluded = {"/health", "/metrics", "/api/health", "/api/cache/stats"}
    if path in excluded:
        return await coro
    return await asyncio.wait_for(coro, timeout=settings.request_timeout)
