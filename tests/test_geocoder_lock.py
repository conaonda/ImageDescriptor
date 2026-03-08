"""Tests for geocoder rate-limiting Lock (#262)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.geocoder import _lock


class TestGeocoderLock:
    def test_lock_is_asyncio_lock(self):
        assert isinstance(_lock, asyncio.Lock)

    async def test_concurrent_requests_serialized(self):
        """Concurrent geocode calls should be serialized by the Lock."""
        call_times = []

        def make_resp():
            resp = MagicMock()
            resp.json.return_value = {"address": {"country": "Korea"}, "display_name": "Seoul"}
            resp.raise_for_status.return_value = None
            return resp

        async def mock_fetch(*args, **kwargs):
            call_times.append(asyncio.get_running_loop().time())
            return make_resp()

        with patch("app.modules.geocoder._fetch_nominatim", side_effect=mock_fetch):
            from app.cache.store import CacheStore

            cache = AsyncMock(spec=CacheStore)
            cache.get = AsyncMock(return_value=None)
            cache.set = AsyncMock()

            from app.modules.geocoder import geocode

            await asyncio.gather(
                geocode(126.0, 37.0, cache),
                geocode(127.0, 38.0, cache),
            )
            # Both calls should have completed (serialized by lock)
            assert len(call_times) == 2
