"""Tests for Supabase get_client() double-check locking (#264)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestSupabaseDoubleCheckLocking:
    @pytest.fixture(autouse=True)
    def reset_client(self):
        import app.db.supabase as mod

        mod._client = None
        mod._consecutive_failures = 0
        mod._last_failure_time = 0.0
        mod._lock = None
        yield
        mod._client = None
        mod._consecutive_failures = 0
        mod._last_failure_time = 0.0
        mod._lock = None

    async def test_concurrent_get_client_creates_once(self):
        """Multiple concurrent get_client() calls should only create one client."""
        create_count = 0
        mock_client = AsyncMock()

        async def mock_acreate(*args, **kwargs):
            nonlocal create_count
            create_count += 1
            await asyncio.sleep(0.01)  # simulate slow init
            return mock_client

        with (
            patch("app.db.supabase.acreate_client", side_effect=mock_acreate),
            patch("app.db.supabase.settings") as mock_settings,
        ):
            mock_settings.supabase_url = "http://test"
            mock_settings.supabase_service_key = "key"
            mock_settings.supabase_reconnect_backoff_base = 1.0
            mock_settings.supabase_reconnect_backoff_max = 30.0

            from app.db.supabase import get_client

            results = await asyncio.gather(*[get_client() for _ in range(5)])
            assert create_count == 1
            assert all(r is mock_client for r in results)

    async def test_get_lock_returns_same_instance(self):
        from app.db.supabase import _get_lock

        lock1 = _get_lock()
        lock2 = _get_lock()
        assert lock1 is lock2
        assert isinstance(lock1, asyncio.Lock)
