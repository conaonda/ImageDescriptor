import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_mod
from app.api.routes import limiter as routes_limiter
from app.api.schemas import DescribeResponse
from app.cache.store import CacheStore
from app.main import app


@pytest.fixture
async def client_with_cache(tmp_path):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache
    routes_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": os.environ["API_KEY"]},
    ) as c:
        yield c
    routes_limiter.reset()
    await cache.close()


def _make_item(lon=126.978, lat=37.566):
    return {
        "thumbnail": "https://example.com/img.jpg",
        "coordinates": [lon, lat],
        "captured_at": "2025-01-15",
    }


def _mock_response():
    return DescribeResponse(description="test description")


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
    return_value=_mock_response(),
)
async def test_batch_success(mock_compose, client_with_cache):
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item(), _make_item()]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    assert len(data["results"]) == 2
    assert data["results"][0]["index"] == 0
    assert data["results"][0]["result"]["description"] == "test description"


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
)
async def test_batch_partial_failure(mock_compose, client_with_cache):
    mock_compose.side_effect = [
        _mock_response(),
        Exception("external service failed"),
    ]
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item(), _make_item()]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert data["results"][0]["result"] is not None
    assert data["results"][1]["error"] == "external service failed"


async def test_batch_empty_array(client_with_cache):
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": []},
    )
    assert resp.status_code == 422


async def test_batch_exceeds_max(client_with_cache):
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item() for _ in range(11)]},
    )
    assert resp.status_code == 422


async def test_batch_no_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.post(
            "/api/v1/describe/batch",
            json={"items": [_make_item()]},
        )
    assert resp.status_code == 401


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
    return_value=_mock_response(),
)
async def test_batch_thumbnail_too_large(mock_compose, client_with_cache):
    large_item = {
        "thumbnail": "x" * (5 * 1024 * 1024 + 1),
        "coordinates": [126.978, 37.566],
    }
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item(), large_item]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert "too large" in data["results"][1]["error"].lower()


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
)
async def test_batch_interrupted_on_shutdown(mock_compose, client_with_cache, monkeypatch):
    """Batch marks remaining items as interrupted when shutdown begins mid-batch."""
    call_count = 0

    async def _compose_with_shutdown(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate shutdown starting after first item completes
            monkeypatch.setattr(main_mod, "_shutting_down", True)
        return _mock_response()

    mock_compose.side_effect = _compose_with_shutdown

    # Initialize shutdown primitives
    main_mod._in_flight_lock = asyncio.Lock()
    main_mod._drain_event = asyncio.Event()
    main_mod._drain_event.set()

    try:
        resp = await client_with_cache.post(
            "/api/v1/describe/batch",
            json={"items": [_make_item(), _make_item(), _make_item()]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 1
        # Remaining items should be marked as interrupted
        assert data["results"][1]["error"] is not None
        assert "interrupted" in data["results"][1]["error"]
        assert data["results"][2]["error"] is not None
        assert "interrupted" in data["results"][2]["error"]
    finally:
        main_mod._shutting_down = False


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
)
async def test_batch_failed_count_includes_interrupted(mock_compose, client_with_cache, monkeypatch):
    """interrupted items are separated from failed in BatchDescribeResponse."""
    call_count = 0

    async def _compose_with_shutdown(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            monkeypatch.setattr(main_mod, "_shutting_down", True)
        return _mock_response()

    mock_compose.side_effect = _compose_with_shutdown
    main_mod._in_flight_lock = asyncio.Lock()
    main_mod._drain_event = asyncio.Event()
    main_mod._drain_event.set()

    try:
        resp = await client_with_cache.post(
            "/api/v1/describe/batch",
            json={"items": [_make_item(), _make_item(), _make_item()]},
        )
        data = resp.json()
        # 1 succeeded, 2 interrupted, 0 failed
        assert data["succeeded"] == 1
        assert data["interrupted"] == 2
        assert data["failed"] == 0
    finally:
        main_mod._shutting_down = False


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
    return_value=_mock_response(),
)
async def test_batch_active_jobs_gauge_zeroed_after_completion(mock_compose, client_with_cache):
    """active_batch_jobs gauge returns to pre-call level after batch processing completes."""
    from app.utils.metrics import get_active_batch_count

    before = get_active_batch_count()
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item(), _make_item()]},
    )
    assert resp.status_code == 200
    assert get_active_batch_count() == before


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
    side_effect=Exception("service error"),
)
async def test_batch_active_jobs_gauge_zeroed_on_exception(mock_compose, client_with_cache):
    """active_batch_jobs gauge is decremented even when batch items raise exceptions."""
    from app.utils.metrics import get_active_batch_count

    before = get_active_batch_count()
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item()]},
    )
    assert resp.status_code == 200
    assert get_active_batch_count() == before


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
    return_value=_mock_response(),
)
async def test_batch_success_interrupted_is_zero(mock_compose, client_with_cache):
    """interrupted field is 0 when no shutdown occurs during batch."""
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item(), _make_item()]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["interrupted"] == 0
    assert data["failed"] == 0


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
)
async def test_batch_partial_failure_interrupted_is_zero(mock_compose, client_with_cache):
    """interrupted field is 0 when items fail due to exceptions (not shutdown)."""
    mock_compose.side_effect = [
        _mock_response(),
        Exception("external service failed"),
    ]
    resp = await client_with_cache.post(
        "/api/v1/describe/batch",
        json={"items": [_make_item(), _make_item()]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert data["interrupted"] == 0


@patch(
    "app.api.routes.compose_description",
    new_callable=AsyncMock,
)
async def test_batch_mixed_failed_and_interrupted(mock_compose, client_with_cache, monkeypatch):
    """failed and interrupted are counted separately when both occur in one batch."""
    call_count = 0

    async def _compose_with_shutdown(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_response()
        if call_count == 2:
            monkeypatch.setattr(main_mod, "_shutting_down", True)
            raise Exception("real failure")
        return _mock_response()

    mock_compose.side_effect = _compose_with_shutdown
    main_mod._in_flight_lock = asyncio.Lock()
    main_mod._drain_event = asyncio.Event()
    main_mod._drain_event.set()

    try:
        resp = await client_with_cache.post(
            "/api/v1/describe/batch",
            # 4 items: item0=success, item1=real failure+trigger shutdown, items2-3=interrupted
            json={"items": [_make_item(), _make_item(), _make_item(), _make_item()]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 4
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        assert data["interrupted"] == 2
        assert data["failed"] + data["succeeded"] + data["interrupted"] == data["total"]
    finally:
        main_mod._shutting_down = False
