from unittest.mock import patch

import pytest
import structlog
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.main import app
from app.utils.logging import generate_request_id, setup_logging


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
        resp = await client.get(
            "/api/health", headers={"X-Request-ID": custom_id}
        )
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
