"""Tests for cache error handling — SQLite failures should not propagate."""

from unittest.mock import AsyncMock

import aiosqlite
import pytest

from app.cache.store import CacheStore


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "cache.db"))
    await store.init()
    yield store
    await store.close()


def _make_failing_execute(exc):
    """Create a mock execute that raises inside async with."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _execute(*args, **kwargs):
        raise exc
        yield  # pragma: no cover

    return _execute


class TestCacheErrorHandling:
    async def test_get_returns_none_on_sqlite_error(self, cache):
        cache._db.execute = _make_failing_execute(aiosqlite.DatabaseError("disk I/O error"))
        result = await cache.get("geocode:1:2")
        assert result is None

    async def test_set_does_not_raise_on_sqlite_error(self, cache):
        cache._db.execute = AsyncMock(side_effect=aiosqlite.DatabaseError("disk full"))
        await cache.set("geocode:1:2", {"data": "test"})

    async def test_cleanup_returns_zero_on_sqlite_error(self, cache):
        cache._db.execute = _make_failing_execute(aiosqlite.DatabaseError("locked"))
        result = await cache.cleanup_expired()
        assert result == 0

    async def test_get_returns_none_on_os_error(self, cache):
        cache._db.execute = _make_failing_execute(OSError("permission denied"))
        result = await cache.get("geocode:1:2")
        assert result is None

    async def test_set_does_not_raise_on_os_error(self, cache):
        cache._db.execute = AsyncMock(side_effect=OSError("read-only filesystem"))
        await cache.set("geocode:1:2", {"data": "test"})

    async def test_get_returns_none_on_json_decode_error(self, cache):
        """Corrupted JSON in cache should return None, not raise."""
        await cache._db.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            ("geocode:corrupt", "not-valid-json{{{", None),
        )
        await cache._db.commit()
        result = await cache.get("geocode:corrupt")
        assert result is None

    async def test_ping_returns_false_on_db_error(self, cache):
        cache._db.execute = _make_failing_execute(aiosqlite.DatabaseError("db error"))
        assert await cache.ping() is False
