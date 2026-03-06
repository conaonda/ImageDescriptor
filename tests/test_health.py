"""Health endpoint dependency check tests for #91."""

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
    resp = await health_client.get("/api/health")
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
        resp = await c.get("/api/health")
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
        resp = await c.get("/api/health")

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
        resp = await c.get("/api/health")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["supabase"] == "fail"
    assert data["checks"]["cache"] == "fail"
