"""Tests for individual data endpoints: /geocode, /landcover, /context."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.main import app


@pytest.fixture
async def auth_client(tmp_path):
    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache
    api_key = os.environ["API_KEY"]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as c:
        yield c
    await cache.close()


async def test_geocode_endpoint(auth_client):
    mock_result = {
        "country": "South Korea",
        "country_code": "kr",
        "region": "Seoul",
        "city": "Seoul",
        "place_name": "Seoul, South Korea",
        "lat": 37.5,
        "lon": 127.0,
    }
    with patch("app.modules.geocoder.geocode", new_callable=AsyncMock, return_value=mock_result):
        resp = await auth_client.post(
            "/api/geocode",
            json={"coordinates": [127.0, 37.5], "thumbnail": "http://example.com/img.png"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["country"] == "South Korea"


async def test_landcover_endpoint(auth_client):
    mock_result = {
        "classes": [{"type": "forest", "label": "산림", "percentage": 100}],
        "summary": "산림 100%",
    }
    with patch(
        "app.modules.landcover.get_land_cover",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = await auth_client.post(
            "/api/landcover",
            json={"coordinates": [127.0, 37.5], "thumbnail": "http://example.com/img.png"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["classes"][0]["type"] == "forest"


async def test_context_endpoint(auth_client):
    mock_result = {
        "events": [
            {
                "title": "Test event",
                "date": "2024-01-01",
                "source_url": "https://example.com",
                "relevance": "high",
            }
        ],
        "summary": "test context",
    }
    with patch(
        "app.modules.context.research_context",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = await auth_client.post(
            "/api/context",
            json={
                "coordinates": [127.0, 37.5],
                "thumbnail": "http://example.com/img.png",
                "captured_at": "2024-01-01",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == "test context"
