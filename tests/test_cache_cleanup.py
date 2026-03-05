import time

import pytest

from app.cache.store import CacheStore


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


class TestCleanupExpired:
    async def test_removes_expired_entries(self, cache):
        await cache.set("geo:expired1", {"v": 1}, ttl_days=0)
        await cache._db.execute(
            "UPDATE cache SET expires_at = ? WHERE key = ?",
            (time.time() - 100, "geo:expired1"),
        )
        await cache._db.commit()
        await cache.set("geo:valid", {"v": 2}, ttl_days=30)

        deleted = await cache.cleanup_expired()
        assert deleted == 1

        assert await cache.get("geo:expired1") is None
        assert await cache.get("geo:valid") == {"v": 2}

    async def test_no_expired_entries(self, cache):
        await cache.set("geo:valid", {"v": 1}, ttl_days=30)
        deleted = await cache.cleanup_expired()
        assert deleted == 0

    async def test_entries_without_expiry_not_removed(self, cache):
        await cache.set("geo:permanent", {"v": 1})
        deleted = await cache.cleanup_expired()
        assert deleted == 0
        assert await cache.get("geo:permanent") == {"v": 1}

    async def test_multiple_expired_entries(self, cache):
        for i in range(5):
            await cache.set(f"geo:expired{i}", {"v": i}, ttl_days=0)
            await cache._db.execute(
                "UPDATE cache SET expires_at = ? WHERE key = ?",
                (time.time() - 100, f"geo:expired{i}"),
            )
        await cache._db.commit()

        deleted = await cache.cleanup_expired()
        assert deleted == 5
