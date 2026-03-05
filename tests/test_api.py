import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture
async def client_with_cache(tmp_path):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
    await cache.close()


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


async def test_describe_no_api_key(client):
    resp = await client.post(
        "/api/describe",
        json={
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        },
    )
    assert resp.status_code == 401


async def test_describe_invalid_coordinates(client):
    resp = await client.post(
        "/api/describe",
        json={
            "thumbnail": "dGVzdA==",
            "coordinates": [999, 999],
            "captured_at": "2025-06-15T00:00:00Z",
        },
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "bbox",
    [
        [999, 0, 10, 10],        # west out of range
        [0, -100, 10, 10],       # south out of range
        [10, 0, 5, 10],          # west >= east
        [0, 10, 10, 5],          # south >= north
    ],
)
async def test_describe_invalid_bbox(client, bbox):
    resp = await client.post(
        "/api/describe",
        json={
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "bbox": bbox,
        },
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 422


def test_describe_bbox_null_accepted():
    from app.api.schemas import DescribeRequest

    req = DescribeRequest(
        thumbnail="dGVzdA==",
        coordinates=[126.978, 37.566],
        bbox=None,
    )
    assert req.bbox is None


async def test_describe_thumbnail_too_large(client):
    resp = await client.post(
        "/api/describe",
        json={
            "thumbnail": "x" * (5 * 1024 * 1024 + 1),
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        },
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 422


async def test_get_description_no_auth(client):
    resp = await client.get("/api/descriptions/some-id")
    assert resp.status_code == 401


@pytest.mark.parametrize("endpoint", ["/api/geocode", "/api/landcover", "/api/context"])
async def test_invalid_coordinates_on_sub_endpoints(client, endpoint):
    resp = await client.post(
        endpoint,
        json={
            "thumbnail": "dGVzdA==",
            "coordinates": [999, 999],
        },
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("endpoint", ["/api/geocode", "/api/landcover", "/api/context"])
async def test_valid_coordinates_require_auth_on_sub_endpoints(client, endpoint):
    resp = await client.post(
        endpoint,
        json={
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
        },
    )
    assert resp.status_code == 401


async def test_cache_stats_endpoint(client_with_cache):
    resp = await client_with_cache.get("/api/cache/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "entry_count" in data
    assert "total_bytes" in data
    assert "modules" in data
    assert data["entry_count"] == 0
    assert data["modules"] == {}


async def test_cache_stats_after_hit_miss(client_with_cache):
    cache = app.state.cache
    # miss
    result = await cache.get("geocode:127:37")
    assert result is None
    # set + hit
    await cache.set("geocode:127:37", {"place": "Seoul"})
    result = await cache.get("geocode:127:37")
    assert result is not None

    resp = await client_with_cache.get("/api/cache/stats")
    data = resp.json()
    assert data["entry_count"] == 1
    geocode_stats = data["modules"]["geocode"]
    assert geocode_stats["hits"] == 1
    assert geocode_stats["misses"] == 1
    assert geocode_stats["hit_rate"] == 0.5
