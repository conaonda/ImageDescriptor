"""Graceful shutdown tests for #193 / #203."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_mod
from app.cache.store import CacheStore
from app.config import Settings
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
    resp = await shutdown_client.post("/api/v1/describe", json={})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Server is shutting down"
    assert resp.json()["status"] == 503


async def test_health_shows_shutting_down_status(shutdown_client, monkeypatch):
    """Health endpoint remains accessible and shows shutting_down status during shutdown."""
    monkeypatch.setattr(main_mod, "_shutting_down", True)
    resp = await shutdown_client.get("/api/v1/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "shutting_down"


async def test_normal_requests_pass_when_not_shutting_down(shutdown_client):
    resp = await shutdown_client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_in_flight_counter_tracks_requests(shutdown_client):
    """In-flight counter increments and decrements around requests."""
    assert main_mod._in_flight == 0
    resp = await shutdown_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert main_mod._in_flight == 0


async def test_drain_event_set_when_no_requests(shutdown_client):
    """Drain event is set when no requests are in flight."""
    assert main_mod._drain_event.is_set()


async def test_is_shutting_down_helper():
    """is_shutting_down() reflects the global flag."""
    original = main_mod._shutting_down
    try:
        main_mod._shutting_down = False
        assert main_mod.is_shutting_down() is False
        main_mod._shutting_down = True
        assert main_mod.is_shutting_down() is True
    finally:
        main_mod._shutting_down = original


def test_shutdown_timeout_configurable():
    """shutdown_timeout is configurable via Settings."""
    s = Settings(
        google_ai_api_key="k", supabase_url="https://x.supabase.co",
        supabase_service_key="k", api_key="k", shutdown_timeout=60,
    )
    assert s.shutdown_timeout == 60


def test_shutdown_timeout_default():
    """shutdown_timeout defaults to 30 seconds."""
    s = Settings(
        google_ai_api_key="k", supabase_url="https://x.supabase.co",
        supabase_service_key="k", api_key="k",
    )
    assert s.shutdown_timeout == 30


def test_shutdown_batch_timeout_configurable():
    """shutdown_batch_timeout is configurable via Settings."""
    s = Settings(
        google_ai_api_key="k", supabase_url="https://x.supabase.co",
        supabase_service_key="k", api_key="k", shutdown_batch_timeout=120,
    )
    assert s.shutdown_batch_timeout == 120


def test_shutdown_batch_timeout_default():
    """shutdown_batch_timeout defaults to 60 seconds."""
    s = Settings(
        google_ai_api_key="k", supabase_url="https://x.supabase.co",
        supabase_service_key="k", api_key="k",
    )
    assert s.shutdown_batch_timeout == 60


@patch("app.db.supabase.ping", new_callable=AsyncMock, return_value=True)
async def test_lifespan_drain_exits_when_no_batch_jobs(mock_ping, tmp_path, monkeypatch):
    """Lifespan shutdown drain completes immediately when no batch jobs are active."""
    from app.main import lifespan
    from app.config import settings

    monkeypatch.setattr(settings, "cache_db_path", str(tmp_path / "drain_test.db"))

    try:
        async with lifespan(app):
            # Simulate SIGTERM during operation: no batch jobs are running
            main_mod._shutting_down = True
        # If we reach here without TimeoutError, drain exited correctly
    finally:
        main_mod._shutting_down = False


@patch("app.db.supabase.ping", new_callable=AsyncMock, return_value=True)
async def test_lifespan_drain_waits_for_batch_jobs(mock_ping, tmp_path, monkeypatch):
    """Lifespan shutdown drain waits until active_batch_jobs drops to 0."""
    from app.main import lifespan
    from app.config import settings
    from app.utils.metrics import batch_job_dec, batch_job_inc

    monkeypatch.setattr(settings, "cache_db_path", str(tmp_path / "drain_wait_test.db"))
    monkeypatch.setattr(settings, "shutdown_batch_timeout", 2)

    released = asyncio.Event()

    async def _release_job():
        await asyncio.sleep(0.3)
        batch_job_dec()
        released.set()

    try:
        async with lifespan(app):
            # Simulate one active batch job during shutdown
            batch_job_inc()
            main_mod._shutting_down = True
            asyncio.create_task(_release_job())
        # Drain should have waited until the gauge dropped to 0
        assert released.is_set()
    finally:
        main_mod._shutting_down = False
