"""Graceful shutdown tests for #108."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_mod
from app.cache.store import CacheStore
from app.main import app


@pytest.fixture
async def shutdown_client(tmp_path, monkeypatch):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache

    import app.db.supabase as supabase_mod

    async def _ok():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _ok)

    # Initialize asyncio primitives in the event loop (required when not using lifespan)
    main_mod._in_flight_lock = asyncio.Lock()
    main_mod._drain_event = asyncio.Event()
    main_mod._drain_event.set()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    # Reset shutdown state
    main_mod._shutting_down = False
    main_mod._in_flight = 0
    main_mod._drain_event.set()
    await cache.close()


async def test_shutdown_rejects_new_requests(shutdown_client, monkeypatch):
    """Non-system endpoints return 503 during shutdown."""
    monkeypatch.setattr(main_mod, "_shutting_down", True)
    resp = await shutdown_client.post("/api/describe", json={})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Server is shutting down"


async def test_health_shows_shutting_down_status(shutdown_client, monkeypatch):
    """Health endpoint remains accessible and shows shutting_down status during shutdown."""
    monkeypatch.setattr(main_mod, "_shutting_down", True)
    resp = await shutdown_client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "shutting_down"


async def test_normal_requests_pass_when_not_shutting_down(shutdown_client):
    resp = await shutdown_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
