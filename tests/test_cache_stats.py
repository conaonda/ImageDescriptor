import time
from unittest.mock import patch

import pytest

from app.cache.store import CacheStore


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "cache.db"))
    await store.init()
    yield store
    await store.close()


class TestCacheStore:
    async def test_get_returns_none_for_missing_key(self, cache):
        result = await cache.get("geocode:0:0")
        assert result is None

    async def test_set_and_get(self, cache):
        await cache.set("geocode:127:37", {"place": "Seoul"})
        result = await cache.get("geocode:127:37")
        assert result == {"place": "Seoul"}

    async def test_expired_entry_returns_none(self, cache):
        await cache.set("geocode:1:1", {"x": 1}, ttl_days=1)
        # Simulate expiration
        future = time.time() + 2 * 86400
        with patch("app.cache.store.time") as mock_time:
            mock_time.time.return_value = future
            result = await cache.get("geocode:1:1")
        assert result is None

    async def test_ttl_none_means_no_expiration(self, cache):
        await cache.set("geocode:2:2", {"x": 2}, ttl_days=None)
        result = await cache.get("geocode:2:2")
        assert result == {"x": 2}

    async def test_ttl_seconds_sets_expiration(self, cache):
        await cache.set("geocode:4:4", {"x": 4}, ttl_seconds=3600)
        result = await cache.get("geocode:4:4")
        assert result == {"x": 4}
        # Simulate expiration
        future = time.time() + 7200
        with patch("app.cache.store.time") as mock_time:
            mock_time.time.return_value = future
            result = await cache.get("geocode:4:4")
        assert result is None

    async def test_overwrite_existing_key(self, cache):
        await cache.set("geocode:3:3", {"v": 1})
        await cache.set("geocode:3:3", {"v": 2})
        result = await cache.get("geocode:3:3")
        assert result == {"v": 2}


class TestCacheStats:
    async def test_empty_cache_stats(self, cache):
        stats = await cache.stats()
        assert stats["entry_count"] == 0
        assert stats["total_bytes"] == 0
        assert stats["modules"] == {}

    async def test_stats_entry_count(self, cache):
        await cache.set("geocode:a", {"x": 1})
        await cache.set("geocode:b", {"x": 2})
        await cache.set("landcover:c", {"x": 3})
        stats = await cache.stats()
        assert stats["entry_count"] == 3

    async def test_stats_total_bytes_nonzero(self, cache):
        await cache.set("geocode:a", {"place": "Seoul"})
        stats = await cache.stats()
        assert stats["total_bytes"] > 0

    async def test_stats_tracks_hits_and_misses(self, cache):
        await cache.set("geocode:127:37", {"place": "Seoul"})
        await cache.get("geocode:127:37")  # hit
        await cache.get("geocode:0:0")  # miss

        stats = await cache.stats()
        geocode = stats["modules"]["geocode"]
        assert geocode["hits"] == 1
        assert geocode["misses"] == 1
        assert geocode["hit_rate"] == 0.5

    async def test_stats_multiple_modules(self, cache):
        await cache.set("geocode:a", {"x": 1})
        await cache.get("geocode:a")  # hit
        await cache.get("landcover:a")  # miss

        stats = await cache.stats()
        assert "geocode" in stats["modules"]
        assert "landcover" in stats["modules"]
        assert stats["modules"]["geocode"]["hits"] == 1
        assert stats["modules"]["landcover"]["misses"] == 1

    async def test_module_from_key_unknown(self, cache):
        await cache.get("noprefix")  # miss, module = "unknown"
        stats = await cache.stats()
        assert "unknown" in stats["modules"]

    async def test_hit_rate_zero_when_all_misses(self, cache):
        await cache.get("geocode:x")
        stats = await cache.stats()
        assert stats["modules"]["geocode"]["hit_rate"] == 0.0


class TestCacheStatsEndpoint:
    @pytest.fixture
    async def client(self, tmp_path):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        store = CacheStore(str(tmp_path / "cache.db"))
        await store.init()
        app.state.cache = store
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
        await store.close()

    async def test_endpoint_returns_200(self, client):
        resp = await client.get("/api/v1/cache/stats")
        assert resp.status_code == 200

    async def test_endpoint_json_structure(self, client):
        resp = await client.get("/api/v1/cache/stats")
        data = resp.json()
        assert "entry_count" in data
        assert "total_bytes" in data
        assert "modules" in data
