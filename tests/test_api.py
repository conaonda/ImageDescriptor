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


async def test_health(client_with_cache):
    with pytest.MonkeyPatch.context() as mp:
        import app.db.supabase as supabase_mod

        async def _mock_ping():
            return True

        mp.setattr(supabase_mod, "ping", _mock_ping)
        resp = await client_with_cache.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["checks"]["cache"] == "ok"
    assert data["checks"]["supabase"] == "ok"


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
        [999, 0, 10, 10],  # west out of range
        [0, -100, 10, 10],  # south out of range
        [10, 0, 5, 10],  # west >= east
        [0, 10, 10, 5],  # south >= north
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


async def test_rate_limit_returns_429(tmp_path):
    """Rate limit exceeded returns 429 with appropriate headers."""
    from unittest.mock import patch

    from app.cache.store import CacheStore
    from app.main import app, limiter

    cache = CacheStore(str(tmp_path / "test.db"))
    await cache.init()
    app.state.cache = cache

    limiter.reset()
    try:
        with patch("app.config.settings.rate_limit", "1/minute"):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as c:
                api_key = os.environ["API_KEY"]
                headers = {"X-API-Key": api_key}
                body = {
                    "thumbnail": "dGVzdA==",
                    "coordinates": [126.978, 37.566],
                    "captured_at": "2025-06-15T00:00:00Z",
                }
                # First request consumes the 1/minute limit
                await c.post("/api/describe", json=body, headers=headers)
                # Second request should be rate limited
                resp2 = await c.post("/api/describe", json=body, headers=headers)
                assert resp2.status_code == 429
    finally:
        limiter.reset()
        await cache.close()


async def test_health_no_rate_limit(client_with_cache, monkeypatch):
    """Health endpoint should not be rate limited."""
    import app.db.supabase as supabase_mod

    async def _mock_ping():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _mock_ping)
    for _ in range(5):
        resp = await client_with_cache.get("/api/health")
        assert resp.status_code == 200


async def test_request_id_header(client_with_cache, monkeypatch):
    import app.db.supabase as supabase_mod

    async def _mock_ping():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _mock_ping)
    resp = await client_with_cache.get("/api/health")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) == 16


async def test_request_id_passthrough(client_with_cache, monkeypatch):
    import app.db.supabase as supabase_mod

    async def _mock_ping():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _mock_ping)
    custom_id = "my-custom-request-id"
    resp = await client_with_cache.get("/api/health", headers={"X-Request-ID": custom_id})
    assert resp.headers["x-request-id"] == custom_id


class TestDescribeAndSave:
    async def test_saved_true_when_save_succeeds(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        import app.db.supabase as db_mod
        from app.api.routes import _describe_and_save
        from app.api.schemas import DescribeRequest, DescribeResponse

        mock_result = DescribeResponse(description="test desc")
        monkeypatch.setattr(
            "app.api.routes.compose_description",
            AsyncMock(return_value=mock_result),
        )
        monkeypatch.setattr(db_mod, "save_description", AsyncMock(return_value=True))

        item = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[127.0, 37.0],
            cog_image_id="img-1",
        )
        result = await _describe_and_save(item, MagicMock())

        assert result.saved is True
        assert result.warnings == []

    async def test_saved_false_and_warning_when_save_fails(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        import app.db.supabase as db_mod
        from app.api.routes import _describe_and_save
        from app.api.schemas import DescribeRequest, DescribeResponse

        mock_result = DescribeResponse(description="test desc")
        monkeypatch.setattr(
            "app.api.routes.compose_description",
            AsyncMock(return_value=mock_result),
        )
        monkeypatch.setattr(db_mod, "save_description", AsyncMock(return_value=False))

        item = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[127.0, 37.0],
            cog_image_id="img-1",
        )
        result = await _describe_and_save(item, MagicMock())

        assert result.saved is False
        assert len(result.warnings) == 1
        assert result.warnings[0].module == "supabase"

    async def test_save_not_called_without_cog_image_id(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        import app.db.supabase as db_mod
        from app.api.routes import _describe_and_save
        from app.api.schemas import DescribeRequest, DescribeResponse

        mock_result = DescribeResponse(description="test desc")
        monkeypatch.setattr(
            "app.api.routes.compose_description",
            AsyncMock(return_value=mock_result),
        )
        mock_save = AsyncMock(return_value=True)
        monkeypatch.setattr(db_mod, "save_description", mock_save)

        item = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[127.0, 37.0],
        )
        result = await _describe_and_save(item, MagicMock())

        mock_save.assert_not_awaited()
        assert result.saved is None


class TestDescribeCacheHeaders:
    @pytest.fixture
    async def _mock_describe(self, client_with_cache, monkeypatch):
        from unittest.mock import AsyncMock

        from app.api.schemas import DescribeResponse

        mock_result = DescribeResponse(description="test desc", cached=False)
        monkeypatch.setattr(
            "app.api.routes._describe_and_save",
            AsyncMock(return_value=mock_result),
        )
        return client_with_cache, mock_result

    async def test_describe_returns_etag_header(self, _mock_describe):
        client, _ = _mock_describe
        resp = await client.post(
            "/api/describe",
            json={"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]},
            headers={"X-API-Key": os.environ["API_KEY"]},
        )
        assert resp.status_code == 200
        assert "etag" in resp.headers
        assert resp.headers["cache-control"] == "no-cache"

    async def test_describe_cached_returns_max_age(self, client_with_cache, monkeypatch):
        from unittest.mock import AsyncMock

        from app.api.schemas import DescribeResponse

        mock_result = DescribeResponse(description="cached desc", cached=True)
        monkeypatch.setattr(
            "app.api.routes._describe_and_save",
            AsyncMock(return_value=mock_result),
        )
        resp = await client_with_cache.post(
            "/api/describe",
            json={"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]},
            headers={"X-API-Key": os.environ["API_KEY"]},
        )
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "private, max-age=3600"

    async def test_describe_304_with_matching_etag(self, _mock_describe):
        client, _ = _mock_describe
        body = {"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]}
        headers = {"X-API-Key": os.environ["API_KEY"]}

        resp1 = await client.post("/api/describe", json=body, headers=headers)
        etag = resp1.headers["etag"]

        headers["If-None-Match"] = etag
        resp2 = await client.post("/api/describe", json=body, headers=headers)
        assert resp2.status_code == 304

    async def test_describe_200_with_mismatched_etag(self, _mock_describe):
        client, _ = _mock_describe
        resp = await client.post(
            "/api/describe",
            json={"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]},
            headers={
                "X-API-Key": os.environ["API_KEY"],
                "If-None-Match": '"wrong-etag"',
            },
        )
        assert resp.status_code == 200
