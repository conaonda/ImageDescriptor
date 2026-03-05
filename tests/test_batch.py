import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.schemas import DescribeResponse
from app.cache.store import CacheStore
from app.main import app


@pytest.fixture
async def client_with_cache(tmp_path):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": os.environ["API_KEY"]},
    ) as c:
        yield c
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
        "/api/describe/batch",
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
        "/api/describe/batch",
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
        "/api/describe/batch",
        json={"items": []},
    )
    assert resp.status_code == 422


async def test_batch_exceeds_max(client_with_cache):
    resp = await client_with_cache.post(
        "/api/describe/batch",
        json={"items": [_make_item() for _ in range(11)]},
    )
    assert resp.status_code == 422


async def test_batch_no_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.post(
            "/api/describe/batch",
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
        "/api/describe/batch",
        json={"items": [_make_item(), large_item]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert "too large" in data["results"][1]["error"].lower()
