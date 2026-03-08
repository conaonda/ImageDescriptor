"""Health endpoint dependency check tests for #91, #188, #226."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import app.db.supabase as supabase_mod
from app.cache.store import CacheStore
from app.main import app


@pytest.fixture
async def health_client(tmp_path, monkeypatch):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache

    async def _supabase_ok():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _supabase_ok)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
    await cache.close()


async def test_health_all_ok(health_client):
    resp = await health_client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["checks"]["supabase"] == "ok"
    assert data["checks"]["cache"] == "ok"
    assert "version" in data


async def test_health_supabase_fail(tmp_path, monkeypatch):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache

    async def _supabase_fail():
        return False

    monkeypatch.setattr(supabase_mod, "ping", _supabase_fail)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/v1/health")
    await cache.close()

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["checks"]["supabase"] == "fail"
    assert data["checks"]["cache"] == "ok"


async def test_health_cache_fail(tmp_path, monkeypatch):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    await cache.close()  # close to make ping fail
    app.state.cache = cache

    async def _supabase_ok():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _supabase_ok)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["checks"]["cache"] == "fail"
    assert data["checks"]["supabase"] == "ok"


async def test_health_all_fail(tmp_path, monkeypatch):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    await cache.close()  # close to make ping fail
    app.state.cache = cache

    async def _supabase_fail():
        return False

    monkeypatch.setattr(supabase_mod, "ping", _supabase_fail)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/v1/health")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["supabase"] == "fail"
    assert data["checks"]["cache"] == "fail"


async def test_readiness_probe(health_client):
    resp = await health_client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["checks"]["supabase"] == "ok"
    assert data["checks"]["cache"] == "ok"
    assert "version" in data


async def test_readiness_probe_degraded(tmp_path, monkeypatch):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache

    async def _supabase_fail():
        return False

    monkeypatch.setattr(supabase_mod, "ping", _supabase_fail)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/v1/health/ready")
    await cache.close()

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"


async def test_liveness_probe(health_client):
    resp = await health_client.get("/api/v1/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_liveness_probe_shutting_down(health_client, monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "_shutting_down", True)
    resp = await health_client.get("/api/v1/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "shutting_down"
    monkeypatch.setattr(main_mod, "_shutting_down", False)


async def test_readiness_probe_all_fail(tmp_path, monkeypatch):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    await cache.close()  # close to make ping fail
    app.state.cache = cache

    async def _supabase_fail():
        return False

    monkeypatch.setattr(supabase_mod, "ping", _supabase_fail)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/v1/health/ready")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["supabase"] == "fail"
    assert data["checks"]["cache"] == "fail"


async def test_health_supabase_timeout(tmp_path, monkeypatch):
    """#226: Supabase ping timeout should result in fail, not hang."""
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache

    async def _supabase_hang():
        await asyncio.sleep(60)
        return True

    monkeypatch.setattr(supabase_mod, "ping", _supabase_hang)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/v1/health")
    await cache.close()

    data = resp.json()
    assert data["checks"]["supabase"] == "fail"
    assert data["status"] in ("degraded", "unhealthy")


async def test_health_cache_timeout(tmp_path, monkeypatch):
    """#226: Cache ping timeout should result in fail, not hang."""
    from unittest.mock import AsyncMock

    cache = AsyncMock(spec=CacheStore)

    async def _cache_hang():
        await asyncio.sleep(60)
        return True

    cache.ping = _cache_hang
    app.state.cache = cache

    async def _supabase_ok():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _supabase_ok)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/v1/health")

    data = resp.json()
    assert data["checks"]["cache"] == "fail"
    assert data["status"] in ("degraded", "unhealthy")
