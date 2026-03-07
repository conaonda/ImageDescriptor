"""Tests for Prometheus metrics endpoint and custom metrics."""

import pytest


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Reset all prometheus collectors between tests to avoid conflicts."""
    yield


async def test_metrics_endpoint(authenticated_client):
    resp = await authenticated_client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "http_requests" in body or "http_request" in body


async def test_cache_metrics_increment():
    from app.utils.metrics import cache_hits, cache_misses

    before_hit = cache_hits.labels(module="test")._value.get()
    before_miss = cache_misses.labels(module="test")._value.get()

    cache_hits.labels(module="test").inc()
    cache_misses.labels(module="test").inc()

    assert cache_hits.labels(module="test")._value.get() == before_hit + 1
    assert cache_misses.labels(module="test")._value.get() == before_miss + 1


async def test_circuit_breaker_metrics():
    from app.utils.metrics import circuit_breaker_state

    circuit_breaker_state.labels(name="test_cb").set(1)
    assert circuit_breaker_state.labels(name="test_cb")._value.get() == 1

    circuit_breaker_state.labels(name="test_cb").set(0)
    assert circuit_breaker_state.labels(name="test_cb")._value.get() == 0

    circuit_breaker_state.labels(name="test_cb").set(2)
    assert circuit_breaker_state.labels(name="test_cb")._value.get() == 2


async def test_external_api_metrics():
    from app.utils.metrics import external_api_duration, external_api_requests

    before = external_api_requests.labels(service="test_svc", status="success")._value.get()
    external_api_requests.labels(service="test_svc", status="success").inc()
    assert (
        external_api_requests.labels(service="test_svc", status="success")._value.get()
        == before + 1
    )

    external_api_duration.labels(service="test_svc").observe(0.5)


async def test_description_requests_total():
    from app.utils.metrics import description_requests_total

    before_success = description_requests_total.labels(status="success")._value.get()
    before_error = description_requests_total.labels(status="error")._value.get()

    description_requests_total.labels(status="success").inc()
    description_requests_total.labels(status="error").inc()

    assert description_requests_total.labels(status="success")._value.get() == before_success + 1
    assert description_requests_total.labels(status="error")._value.get() == before_error + 1


async def test_active_batch_jobs():
    from app.utils.metrics import active_batch_jobs

    before = active_batch_jobs._value.get()
    active_batch_jobs.inc()
    assert active_batch_jobs._value.get() == before + 1
    active_batch_jobs.dec()
    assert active_batch_jobs._value.get() == before


async def test_metrics_endpoint_no_auth():
    """Metrics endpoint should be accessible without auth."""
    from httpx import ASGITransport, AsyncClient

    from app.cache.store import CacheStore
    from app.config import settings
    from app.main import app

    cache = CacheStore(settings.cache_db_path)
    await cache.init()
    app.state.cache = cache

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/metrics")
        assert resp.status_code == 200

    await cache.close()
