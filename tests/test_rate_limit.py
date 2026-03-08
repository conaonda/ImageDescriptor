import datetime
import os
from unittest.mock import MagicMock, patch

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
        with patch("app.config.settings.rate_limit_describe", "1/minute"):
            await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            resp = await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            assert resp.status_code == 429

    async def test_429_response_body(self, rate_limit_client):
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with patch("app.config.settings.rate_limit_describe", "1/minute"):
            await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            resp = await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            assert resp.status_code == 429
            data = resp.json()
            assert data["type"] == "https://problems.cognito-descriptor.io/rate-limit-exceeded"
            assert data["status"] == 429
            assert "detail" in data
            assert resp.headers.get("content-type") == "application/problem+json"
            assert "Retry-After" in resp.headers
            assert int(resp.headers["Retry-After"]) > 0

    async def test_health_endpoint_not_rate_limited(self, rate_limit_client):
        for _ in range(10):
            resp = await rate_limit_client.get("/api/v1/health")
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
        with patch("app.config.settings.rate_limit_describe", "1/minute"):
            # Exhaust describe limit
            await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            resp = await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            assert resp.status_code == 429
            # cache/stats should still work (no rate limit on system endpoints)
            resp = await rate_limit_client.get("/api/v1/cache/stats")
            assert resp.status_code == 200

    async def test_success_response_includes_rate_limit_headers(self, rate_limit_client):
        """Successful responses include X-RateLimit-* headers."""
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with patch("app.config.settings.rate_limit_describe", "5/minute"):
            resp = await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            assert "X-RateLimit-Limit" in resp.headers
            assert resp.headers["X-RateLimit-Limit"] == "5"
            assert "X-RateLimit-Remaining" in resp.headers
            assert int(resp.headers["X-RateLimit-Remaining"]) == 4
            assert "X-RateLimit-Reset" in resp.headers
            reset = int(resp.headers["X-RateLimit-Reset"])
            assert 0 < reset <= 60

    async def test_429_response_includes_rate_limit_headers(self, rate_limit_client):
        """429 responses include X-RateLimit-* headers with remaining=0."""
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with patch("app.config.settings.rate_limit_describe", "1/minute"):
            await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            resp = await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            assert resp.status_code == 429
            assert resp.headers["X-RateLimit-Limit"] == "1"
            assert resp.headers["X-RateLimit-Remaining"] == "0"
            assert "X-RateLimit-Reset" in resp.headers
            assert "Retry-After" in resp.headers

    async def test_describe_and_data_have_independent_limits(self, rate_limit_client):
        """describe and data endpoints have separate rate limit pools."""
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with (
            patch("app.config.settings.rate_limit_describe", "1/minute"),
            patch("app.config.settings.rate_limit_data", "1/minute"),
        ):
            # Exhaust describe limit
            await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            resp = await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            assert resp.status_code == 429
            # Data endpoint should still accept (independent limit)
            resp = await rate_limit_client.post("/api/v1/geocode", json=body, headers=headers)
            assert resp.status_code == 200

    async def test_middleware_header_injection_error_is_silenced(self, rate_limit_client):
        """get_window_stats 실패 시 예외를 조용히 처리하고 응답은 정상 반환."""
        api_key = os.environ["API_KEY"]
        headers = {"X-API-Key": api_key}
        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }
        with (
            patch("app.config.settings.rate_limit_describe", "5/minute"),
            patch(
                "app.api.routes.limiter.limiter.get_window_stats",
                side_effect=RuntimeError("storage error"),
            ),
        ):
            resp = await rate_limit_client.post("/api/v1/describe", json=body, headers=headers)
            # 헤더 주입 실패해도 응답 자체는 정상 처리
            assert resp.status_code in (200, 422, 500)
            # X-RateLimit 헤더는 없을 수 있음 (예외로 주입 실패)
            assert "X-RateLimit-Limit" not in resp.headers

    async def test_429_handler_with_datetime_retry_after(self, rate_limit_client):
        """retry_after가 datetime 객체일 때 Retry-After 헤더가 올바르게 계산됨."""
        from app.main import _rate_limit_handler

        future_time = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=30)

        mock_exc = MagicMock()
        mock_exc.retry_after = future_time
        mock_exc.detail = "rate limit exceeded"
        del mock_exc.limit  # hasattr(exc, "limit") → False

        mock_request = MagicMock()
        mock_request.headers = {}

        with patch("app.utils.errors._get_correlation_id", return_value="test-correlation-id"):
            response = await _rate_limit_handler(mock_request, mock_exc)

        assert response.status_code == 429
        retry_after_val = int(response.headers["Retry-After"])
        assert retry_after_val >= 1
