"""Tests for cache error handling — SQLite failures should not propagate."""

from unittest.mock import AsyncMock

import pytest

from app.cache.store import CacheStore


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "cache.db"))
    await store.init()
    yield store
    await store.close()


class TestCacheErrorHandling:
    async def test_get_returns_none_on_sqlite_error(self, cache):
        cache._db.execute = AsyncMock(side_effect=Exception("disk I/O error"))
        result = await cache.get("geocode:1:2")
        assert result is None

    async def test_set_does_not_raise_on_sqlite_error(self, cache):
        cache._db.execute = AsyncMock(side_effect=Exception("disk full"))
        await cache.set("geocode:1:2", {"data": "test"})

    async def test_cleanup_returns_zero_on_sqlite_error(self, cache):
        cache._db.execute = AsyncMock(side_effect=Exception("locked"))
        result = await cache.cleanup_expired()
        assert result == 0
