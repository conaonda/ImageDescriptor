import time
from unittest.mock import patch

import pytest

from app.utils.circuit_breaker import CircuitBreaker


class TestCircuitBreakerGetStatus:
    async def test_closed_status(self):
        cb = CircuitBreaker("geocoder")
        status = await cb.get_status()
        assert status["name"] == "geocoder"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert status["cooldown_remaining"] == 0.0

    async def test_open_status(self):
        cb = CircuitBreaker("geocoder", failure_threshold=2, cooldown_sec=30.0)
        await cb.record_failure()
        await cb.record_failure()
        status = await cb.get_status()
        assert status["state"] == "open"
        assert status["failure_count"] == 2
        assert status["cooldown_remaining"] > 0

    async def test_cooldown_remaining_decreases(self):
        cb = CircuitBreaker("geocoder", failure_threshold=1, cooldown_sec=10.0)
        await cb.record_failure()
        with patch("app.utils.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 5
            status = await cb.get_status()
            assert status["cooldown_remaining"] <= 5.1


class TestCircuitsEndpoint:
    @pytest.fixture
    async def client(self, tmp_path):
        from httpx import ASGITransport, AsyncClient

        from app.cache.store import CacheStore
        from app.main import app

        store = CacheStore(str(tmp_path / "cache.db"))
        await store.init()
        app.state.cache = store
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
        await store.close()

    async def test_endpoint_returns_200(self, client):
        resp = await client.get("/api/v1/circuits")
        assert resp.status_code == 200

    async def test_response_structure(self, client):
        resp = await client.get("/api/v1/circuits")
        data = resp.json()
        assert "breakers" in data
        assert len(data["breakers"]) == 5
        for breaker in data["breakers"]:
            assert "name" in breaker
            assert "state" in breaker
            assert "failure_count" in breaker
            assert "cooldown_remaining" in breaker

    async def test_all_services_present(self, client):
        resp = await client.get("/api/v1/circuits")
        names = {b["name"] for b in resp.json()["breakers"]}
        assert names == {"geocoder", "landcover", "describer", "context", "mission"}
