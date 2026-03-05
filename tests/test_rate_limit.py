import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.main import app, limiter
from app.utils.rate_limit import get_real_ip


@pytest.fixture
async def rate_limit_client(tmp_path):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache
    limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
    limiter.reset()
    await cache.close()


class TestGetRealIp:
    def test_extracts_first_ip_from_forwarded_header(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")],
        }
        request = Request(scope)
        assert get_real_ip(request) == "1.2.3.4"

    def test_returns_single_forwarded_ip(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"10.0.0.1")],
        }
        request = Request(scope)
        assert get_real_ip(request) == "10.0.0.1"

    def test_falls_back_to_client_host(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": ("192.168.1.1", 12345),
        }
        request = Request(scope)
        assert get_real_ip(request) == "192.168.1.1"

    def test_returns_localhost_when_no_client(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
        }
        request = Request(scope)
        assert get_real_ip(request) == "127.0.0.1"


class TestRateLimitMiddleware:
    async def test_rate_limit_returns_429(self, rate_limit_client):
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with patch("app.config.settings.rate_limit", "1/minute"):
            await rate_limit_client.post("/api/describe", json=body, headers=headers)
            resp = await rate_limit_client.post(
                "/api/describe", json=body, headers=headers
            )
            assert resp.status_code == 429

    async def test_429_response_body(self, rate_limit_client):
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with patch("app.config.settings.rate_limit", "1/minute"):
            await rate_limit_client.post("/api/describe", json=body, headers=headers)
            resp = await rate_limit_client.post(
                "/api/describe", json=body, headers=headers
            )
            assert resp.status_code == 429
            data = resp.json()
            assert "error" in data or "detail" in data

    async def test_health_endpoint_not_rate_limited(self, rate_limit_client):
        for _ in range(10):
            resp = await rate_limit_client.get("/api/health")
            assert resp.status_code == 200

    async def test_rate_limit_per_endpoint(self, rate_limit_client):
        """Different endpoints have independent rate limits."""
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with patch("app.config.settings.rate_limit", "1/minute"):
            # Exhaust describe limit
            await rate_limit_client.post("/api/describe", json=body, headers=headers)
            resp = await rate_limit_client.post(
                "/api/describe", json=body, headers=headers
            )
            assert resp.status_code == 429
            # cache/stats should still work (no rate limit)
            resp = await rate_limit_client.get("/api/cache/stats")
            assert resp.status_code == 200
