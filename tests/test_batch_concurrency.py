"""Batch concurrency limit tests for #113."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.config import settings
from app.main import app


@pytest.fixture
async def batch_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "batch_concurrency", 2)
    monkeypatch.setattr(settings, "request_timeout", 30)
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


async def test_batch_concurrency_limited(batch_client, monkeypatch):
    max_concurrent = 0
    current = 0
    lock = asyncio.Lock()

    async def _tracked_compose(item, cache):
        nonlocal max_concurrent, current
        async with lock:
            current += 1
            if current > max_concurrent:
                max_concurrent = current
        await asyncio.sleep(0.1)
        async with lock:
            current -= 1

        from app.api.schemas import DescribeResponse

        return DescribeResponse(
            description="test",
            location=None,
            land_cover=None,
            context=None,
            cached=False,
            warnings=[],
        )

    import app.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "compose_description", _tracked_compose)

    import app.db.supabase as db_mod

    async def _noop_save(**kwargs):
        return True

    monkeypatch.setattr(db_mod, "save_description", _noop_save)

    items = [{"coordinates": [127.0 + i * 0.01, 37.0], "thumbnail": "dGVzdA=="} for i in range(6)]

    resp = await batch_client.post("/api/v1/describe/batch", json={"items": items})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert data["succeeded"] == 6
    assert max_concurrent <= 2


async def test_batch_all_items_processed(batch_client, monkeypatch):
    import app.api.routes as routes_mod
    import app.db.supabase as db_mod

    async def _mock_compose(item, cache):
        from app.api.schemas import DescribeResponse

        return DescribeResponse(
            description="ok",
            location=None,
            land_cover=None,
            context=None,
            cached=False,
            warnings=[],
        )

    async def _noop_save(**kwargs):
        return True

    monkeypatch.setattr(routes_mod, "compose_description", _mock_compose)
    monkeypatch.setattr(db_mod, "save_description", _noop_save)

    items = [{"coordinates": [127.0, 37.0], "thumbnail": "dGVzdA=="} for _ in range(10)]

    resp = await batch_client.post("/api/v1/describe/batch", json={"items": items})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 10
    assert data["succeeded"] == 10


async def test_individual_failure_does_not_affect_others(batch_client, monkeypatch):
    import app.api.routes as routes_mod
    import app.db.supabase as db_mod

    call_count = 0

    async def _sometimes_fail(item, cache):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ValueError("test error")
        from app.api.schemas import DescribeResponse

        return DescribeResponse(
            description="ok",
            location=None,
            land_cover=None,
            context=None,
            cached=False,
            warnings=[],
        )

    async def _noop_save(**kwargs):
        return True

    monkeypatch.setattr(routes_mod, "compose_description", _sometimes_fail)
    monkeypatch.setattr(db_mod, "save_description", _noop_save)

    items = [{"coordinates": [127.0, 37.0], "thumbnail": "dGVzdA=="} for _ in range(5)]

    resp = await batch_client.post("/api/v1/describe/batch", json={"items": items})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert data["succeeded"] == 4
    assert data["failed"] == 1
