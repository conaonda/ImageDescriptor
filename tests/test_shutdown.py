"""Graceful shutdown tests for #108."""

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
    monkeypatch.setattr(main_mod, "_shutting_down", True)
    resp = await shutdown_client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Server is shutting down"


async def test_health_shows_shutting_down_status(shutdown_client, monkeypatch):
    """Health endpoint should show shutting_down when accessed directly (bypass shutdown middleware)."""
    # The shutdown middleware blocks all requests, so we test the function directly
    from app.api.routes import health
    from unittest.mock import MagicMock

    monkeypatch.setattr(main_mod, "_shutting_down", True)

    mock_request = MagicMock()
    mock_request.app.state.cache = shutdown_client._transport.app.state.cache

    resp = await health(mock_request)
    data = resp.body.decode()
    import json

    body = json.loads(data)
    assert body["status"] == "shutting_down"
    assert resp.status_code == 503


async def test_normal_requests_pass_when_not_shutting_down(shutdown_client):
    resp = await shutdown_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
