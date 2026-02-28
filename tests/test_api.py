import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


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
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 400


async def test_describe_thumbnail_too_large(client):
    resp = await client.post(
        "/api/describe",
        json={
            "thumbnail": "x" * (5 * 1024 * 1024 + 1),
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 422


async def test_get_description_no_auth(client):
    resp = await client.get("/api/descriptions/some-id")
    assert resp.status_code == 401
