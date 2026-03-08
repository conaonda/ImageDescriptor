"""Shared httpx.AsyncClient for connection pooling across modules."""

import asyncio

import httpx

from app.config import settings

_client: httpx.AsyncClient | None = None
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Return the module-level lock, creating it lazily (safe in single-threaded asyncio)."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_client() -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient, creating it lazily if needed.

    Uses an asyncio.Lock to prevent race conditions when multiple
    coroutines call this concurrently.
    """
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _get_lock():
        # Double-check after acquiring lock
        if _client is not None and not _client.is_closed:
            return _client
        _client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
            timeout=httpx.Timeout(settings.timeout_http_client),
        )
        return _client


async def close_client() -> None:
    """Close the shared client. Called during app shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
