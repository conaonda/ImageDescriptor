"""Request timeout middleware tests for #112."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.config import settings
from app.main import app


@pytest.fixture
async def timeout_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "request_timeout", 1)
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache

    api_key = "test-key"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as c:
        yield c
    await cache.close()


async def test_timeout_returns_504(timeout_client, monkeypatch):
    async def _slow_compose(*args, **kwargs):
        await asyncio.sleep(5)

    import app.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "compose_description", _slow_compose)

    resp = await timeout_client.post(
        "/api/describe",
        json={
            "coordinates": [127.0, 37.0],
            "thumbnail": "dGVzdA==",
        },
    )
    assert resp.status_code == 504
    assert resp.json()["detail"] == "Gateway Timeout"


async def test_system_endpoints_skip_timeout(timeout_client):
    resp = await timeout_client.get("/api/health")
    assert resp.status_code == 200


async def test_normal_request_not_affected(timeout_client, monkeypatch):
    import app.db.supabase as supabase_mod

    async def _ok():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _ok)

    resp = await timeout_client.get("/api/health")
    assert resp.status_code == 200
