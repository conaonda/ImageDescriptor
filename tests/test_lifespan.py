"""Tests for app.main lifespan and cache_cleanup_loop."""

import asyncio
from unittest.mock import AsyncMock

import app.main as main_mod
from app.cache.store import CacheStore


async def test_lifespan_initializes_and_cleans_up(tmp_path, monkeypatch):
    """Lifespan should init cache, create cleanup task, and clean up on exit."""
    monkeypatch.setattr(main_mod.settings, "cache_db_path", str(tmp_path / "test.db"))

    from fastapi import FastAPI

    test_app = FastAPI(lifespan=main_mod.lifespan)

    async with main_mod.lifespan(test_app):
        assert hasattr(test_app.state, "cache")
        assert isinstance(test_app.state.cache, CacheStore)
        assert main_mod._in_flight_lock is not None
        assert main_mod._drain_event is not None
        assert main_mod._shutting_down is False

    # After lifespan exit, cache should be closed


async def test_lifespan_shutdown_drain(tmp_path, monkeypatch):
    """During shutdown, lifespan should wait for in-flight requests to drain."""
    monkeypatch.setattr(main_mod.settings, "cache_db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_mod.settings, "shutdown_timeout", 1)

    from fastapi import FastAPI

    test_app = FastAPI(lifespan=main_mod.lifespan)

    async with main_mod.lifespan(test_app):
        main_mod._shutting_down = True
        # drain_event is already set (no in-flight), so it should drain immediately

    main_mod._shutting_down = False


async def test_lifespan_shutdown_drain_timeout(tmp_path, monkeypatch):
    """When drain times out, lifespan should log warning and continue."""
    monkeypatch.setattr(main_mod.settings, "cache_db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_mod.settings, "shutdown_timeout", 0.01)

    from fastapi import FastAPI

    test_app = FastAPI(lifespan=main_mod.lifespan)

    async with main_mod.lifespan(test_app):
        main_mod._shutting_down = True
        # Simulate an in-flight request by clearing drain event
        main_mod._drain_event.clear()
        main_mod._in_flight = 1

    main_mod._shutting_down = False
    main_mod._in_flight = 0


async def test_cache_cleanup_loop_runs(tmp_path, monkeypatch):
    """Cache cleanup loop should call cleanup_expired."""
    monkeypatch.setattr(main_mod, "CACHE_CLEANUP_INTERVAL_SECONDS", 0.01)

    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    cache.cleanup_expired = AsyncMock()

    task = asyncio.create_task(main_mod._cache_cleanup_loop(cache))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert cache.cleanup_expired.call_count >= 1
    await cache.close()


async def test_cache_cleanup_loop_handles_exception(tmp_path, monkeypatch):
    """Cache cleanup loop should swallow exceptions and continue."""
    monkeypatch.setattr(main_mod, "CACHE_CLEANUP_INTERVAL_SECONDS", 0.01)

    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    cache.cleanup_expired = AsyncMock(side_effect=RuntimeError("db error"))

    task = asyncio.create_task(main_mod._cache_cleanup_loop(cache))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert cache.cleanup_expired.call_count >= 1
    await cache.close()


async def test_is_shutting_down():
    """is_shutting_down should reflect _shutting_down state."""
    original = main_mod._shutting_down
    try:
        main_mod._shutting_down = False
        assert main_mod.is_shutting_down() is False
        main_mod._shutting_down = True
        assert main_mod.is_shutting_down() is True
    finally:
        main_mod._shutting_down = original
