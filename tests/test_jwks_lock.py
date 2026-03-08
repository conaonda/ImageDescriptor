"""Tests for JWKS cache lock (concurrent request deduplication)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth import _get_jwks

FAKE_JWKS = {"keys": [{"kty": "RSA", "kid": "test"}]}


@pytest.fixture(autouse=True)
def reset_jwks_cache():
    """Reset JWKS cache before each test."""
    import app.auth as auth_mod

    auth_mod._jwks_cache = None
    auth_mod._jwks_cache_ts = 0.0
    yield
    auth_mod._jwks_cache = None
    auth_mod._jwks_cache_ts = 0.0


class TestJwksLock:
    async def test_concurrent_requests_single_fetch(self):
        """10 concurrent _get_jwks calls should result in only 1 HTTP fetch."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = FAKE_JWKS
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.http_client.get_client", return_value=mock_client):
            results = await asyncio.gather(*[_get_jwks() for _ in range(10)])

        assert all(r == FAKE_JWKS for r in results)
        assert mock_client.get.call_count == 1

    async def test_cache_expiry_refetches(self):
        """After TTL expires, a new fetch should occur."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = FAKE_JWKS
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("app.http_client.get_client", return_value=mock_client),
            patch("app.auth.settings") as mock_settings,
        ):
            mock_settings.jwks_ttl_seconds = 0.0
            mock_settings.supabase_url = "https://fake.supabase.co"
            result1 = await _get_jwks()
            result2 = await _get_jwks()

        assert result1 == FAKE_JWKS
        assert result2 == FAKE_JWKS
        assert mock_client.get.call_count == 2
