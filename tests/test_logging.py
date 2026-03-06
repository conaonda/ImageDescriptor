from unittest.mock import patch

import pytest
import structlog
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.main import app
from app.utils.logging import (
    _safe_headers,
    _safe_query_params,
    _sanitize_correlation_id,
    _sanitize_request_id,
    generate_correlation_id,
    generate_request_id,
    setup_logging,
)


@pytest.fixture
async def client(tmp_path):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
    await cache.close()


class TestSetupLogging:
    def test_configures_structlog(self):
        setup_logging()
        logger = structlog.get_logger()
        assert logger is not None

    def test_respects_log_level(self):
        with patch("app.utils.logging.settings") as mock_settings:
            mock_settings.log_level = "DEBUG"
            setup_logging()
            logger = structlog.get_logger()
            assert logger is not None

    def test_invalid_log_level_defaults_to_info(self):
        with patch("app.utils.logging.settings") as mock_settings:
            mock_settings.log_level = "INVALID"
            setup_logging()
            # Should not raise; falls back to INFO


class TestGenerateRequestId:
    def test_returns_16_char_hex(self):
        rid = generate_request_id()
        assert len(rid) == 16
        int(rid, 16)  # should not raise

    def test_unique_ids(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100


class TestRequestIdMiddleware:
    async def test_response_includes_request_id(self, client):
        resp = await client.get("/api/health")
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) == 16

    async def test_custom_request_id_passthrough(self, client):
        custom_id = "my-custom-req-id"
        resp = await client.get("/api/health", headers={"X-Request-ID": custom_id})
        assert resp.headers["x-request-id"] == custom_id

    async def test_generated_id_is_hex(self, client):
        resp = await client.get("/api/health")
        rid = resp.headers["x-request-id"]
        int(rid, 16)  # should not raise

    async def test_different_requests_get_different_ids(self, client):
        resp1 = await client.get("/api/health")
        resp2 = await client.get("/api/health")
        assert resp1.headers["x-request-id"] != resp2.headers["x-request-id"]

    async def test_security_headers_present(self, client):
        resp = await client.get("/api/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"

    async def test_invalid_request_id_ignored(self, client):
        resp = await client.get(
            "/api/health",
            headers={"X-Request-ID": "<script>alert(1)</script>"},
        )
        rid = resp.headers["x-request-id"]
        assert rid != "<script>alert(1)</script>"
        assert len(rid) == 16


class TestProcessTimeHeader:
    async def test_response_includes_process_time(self, client):
        resp = await client.get("/api/health")
        assert "x-process-time" in resp.headers
        process_time = float(resp.headers["x-process-time"])
        assert process_time >= 0

    async def test_process_time_is_numeric(self, client):
        resp = await client.get("/api/health")
        float(resp.headers["x-process-time"])  # should not raise


class TestGenerateCorrelationId:
    def test_returns_valid_uuid(self):
        cid = generate_correlation_id()
        import uuid

        parsed = uuid.UUID(cid)
        assert str(parsed) == cid

    def test_unique_ids(self):
        ids = {generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100


class TestSanitizeCorrelationId:
    def test_valid_uuid(self):
        valid = "550e8400-e29b-41d4-a716-446655440000"
        assert _sanitize_correlation_id(valid) == valid

    def test_rejects_invalid(self):
        assert _sanitize_correlation_id("not-a-uuid") is None

    def test_rejects_script_injection(self):
        assert _sanitize_correlation_id("<script>alert(1)</script>") is None

    def test_none_input(self):
        assert _sanitize_correlation_id(None) is None

    def test_empty_string(self):
        assert _sanitize_correlation_id("") is None


class TestCorrelationIdMiddleware:
    async def test_response_includes_correlation_id(self, client):
        resp = await client.get("/api/health")
        assert "x-correlation-id" in resp.headers
        import uuid

        uuid.UUID(resp.headers["x-correlation-id"])  # should not raise

    async def test_custom_correlation_id_passthrough(self, client):
        custom_id = "550e8400-e29b-41d4-a716-446655440000"
        resp = await client.get("/api/health", headers={"X-Correlation-ID": custom_id})
        assert resp.headers["x-correlation-id"] == custom_id

    async def test_invalid_correlation_id_replaced(self, client):
        resp = await client.get(
            "/api/health",
            headers={"X-Correlation-ID": "not-a-valid-uuid"},
        )
        cid = resp.headers["x-correlation-id"]
        assert cid != "not-a-valid-uuid"
        import uuid

        uuid.UUID(cid)  # should be a valid UUID

    async def test_different_requests_get_different_ids(self, client):
        resp1 = await client.get("/api/health")
        resp2 = await client.get("/api/health")
        assert resp1.headers["x-correlation-id"] != resp2.headers["x-correlation-id"]


class TestSafeHeaders:
    def test_redacts_sensitive_headers(self):
        headers = {
            "authorization": "Bearer secret-token",
            "x-api-key": "my-key",
            "cookie": "session=abc",
            "content-type": "application/json",
        }
        safe = _safe_headers(headers)
        assert safe["authorization"] == "[REDACTED]"
        assert safe["x-api-key"] == "[REDACTED]"
        assert safe["cookie"] == "[REDACTED]"
        assert safe["content-type"] == "application/json"

    def test_empty_headers(self):
        assert _safe_headers({}) == {}


class TestSafeQueryParams:
    def test_redacts_api_key(self):
        result = _safe_query_params("api_key=secret123&format=json")
        assert "secret123" not in result
        assert "api_key=[REDACTED]" in result
        assert "format=json" in result

    def test_redacts_token(self):
        result = _safe_query_params("token=abc&page=1")
        assert "abc" not in result
        assert "token=[REDACTED]" in result

    def test_empty_string(self):
        assert _safe_query_params("") == ""

    def test_no_sensitive_params(self):
        result = _safe_query_params("page=1&limit=10")
        assert result == "page=1&limit=10"


class TestSanitizeRequestId:
    def test_valid_id(self):
        assert _sanitize_request_id("abc-123_XYZ") == "abc-123_XYZ"

    def test_rejects_script_injection(self):
        assert _sanitize_request_id("<script>") is None

    def test_rejects_too_long(self):
        assert _sanitize_request_id("a" * 200) is None

    def test_none_input(self):
        assert _sanitize_request_id(None) is None

    def test_empty_string(self):
        assert _sanitize_request_id("") is None
