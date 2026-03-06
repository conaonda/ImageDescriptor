import os
from unittest.mock import AsyncMock

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

    async def test_etag_is_deterministic(self, _mock_describe):
        """Same response content must produce identical ETag values."""
        client, _ = _mock_describe
        body = {"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]}
        headers = {"X-API-Key": os.environ["API_KEY"]}

        resp1 = await client.post("/api/describe", json=body, headers=headers)
        resp2 = await client.post("/api/describe", json=body, headers=headers)
        assert resp1.headers["etag"] == resp2.headers["etag"]

    async def test_etag_format_is_quoted_string(self, _mock_describe):
        """ETag must be a quoted string per HTTP spec."""
        client, _ = _mock_describe
        resp = await client.post(
            "/api/describe",
            json={"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]},
            headers={"X-API-Key": os.environ["API_KEY"]},
        )
        etag = resp.headers["etag"]
        assert etag.startswith('"') and etag.endswith('"')
        assert len(etag) == 34  # 32 hex chars + 2 quotes

    async def test_304_includes_etag_header(self, _mock_describe):
        """304 Not Modified response must still include the ETag header."""
        client, _ = _mock_describe
        body = {"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]}
        headers = {"X-API-Key": os.environ["API_KEY"]}

        resp1 = await client.post("/api/describe", json=body, headers=headers)
        etag = resp1.headers["etag"]

        headers["If-None-Match"] = etag
        resp2 = await client.post("/api/describe", json=body, headers=headers)
        assert resp2.status_code == 304
        assert resp2.headers["etag"] == etag

    async def test_304_has_empty_body(self, _mock_describe):
        """304 response must have no content body."""
        client, _ = _mock_describe
        body = {"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]}
        headers = {"X-API-Key": os.environ["API_KEY"]}

        resp1 = await client.post("/api/describe", json=body, headers=headers)
        headers["If-None-Match"] = resp1.headers["etag"]

        resp2 = await client.post("/api/describe", json=body, headers=headers)
        assert resp2.status_code == 304
        assert resp2.content == b""

    async def test_different_content_produces_different_etag(self, client_with_cache, monkeypatch):
        """Different response bodies must produce different ETags."""
        from unittest.mock import AsyncMock

        from app.api.schemas import DescribeResponse

        headers = {"X-API-Key": os.environ["API_KEY"]}
        body = {"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]}

        mock1 = DescribeResponse(description="first description", cached=False)
        monkeypatch.setattr(
            "app.api.routes._describe_and_save",
            AsyncMock(return_value=mock1),
        )
        resp1 = await client_with_cache.post("/api/describe", json=body, headers=headers)

        mock2 = DescribeResponse(description="second description", cached=False)
        monkeypatch.setattr(
            "app.api.routes._describe_and_save",
            AsyncMock(return_value=mock2),
        )
        resp2 = await client_with_cache.post("/api/describe", json=body, headers=headers)

        assert resp1.headers["etag"] != resp2.headers["etag"]

    async def test_200_without_if_none_match_always_returns_body(self, _mock_describe):
        """Request without If-None-Match must always return 200 with full body."""
        client, _ = _mock_describe
        resp = await client.post(
            "/api/describe",
            json={"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]},
            headers={"X-API-Key": os.environ["API_KEY"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "description" in data


async def test_health_degraded_when_supabase_fails(client_with_cache, monkeypatch):
    import app.db.supabase as supabase_mod

    async def _supabase_fail():
        return False

    async def _cache_ok():
        return True

    monkeypatch.setattr(supabase_mod, "ping", _supabase_fail)
    # cache.ping is already ok since it's a real cache
    resp = await client_with_cache.get("/api/health")
    data = resp.json()
    assert data["status"] in ("degraded", "shutting_down")
    assert data["checks"]["supabase"] == "fail"


async def test_health_unhealthy_when_all_fail(client_with_cache, monkeypatch):
    import app.db.supabase as supabase_mod

    async def _fail():
        return False

    monkeypatch.setattr(supabase_mod, "ping", _fail)
    monkeypatch.setattr(app.state.cache, "ping", _fail)
    resp = await client_with_cache.get("/api/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] in ("unhealthy", "shutting_down")


async def test_get_description_not_found(client_with_cache, monkeypatch):
    import app.db.supabase as db_mod

    monkeypatch.setattr(db_mod, "get_description", AsyncMock(return_value=None))
    resp = await client_with_cache.get(
        "/api/descriptions/nonexistent-id",
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert "NOT_FOUND" in str(data)


async def test_get_description_found(client_with_cache, monkeypatch):
    import app.db.supabase as db_mod

    mock_data = {"description": "test", "cog_image_id": "found-id"}
    monkeypatch.setattr(db_mod, "get_description", AsyncMock(return_value=mock_data))
    resp = await client_with_cache.get(
        "/api/descriptions/found-id",
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "test"


async def test_list_descriptions(client_with_cache, monkeypatch):
    import app.db.supabase as db_mod

    mock_result = {"items": [{"cog_image_id": "id-1"}], "total": 1}
    monkeypatch.setattr(db_mod, "list_descriptions", AsyncMock(return_value=mock_result))
    resp = await client_with_cache.get(
        "/api/descriptions",
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["offset"] == 0
    assert data["limit"] == 20


async def test_list_descriptions_no_auth(client):
    resp = await client.get("/api/descriptions")
    assert resp.status_code == 401


async def test_shutdown_middleware_rejects_non_system_paths(client_with_cache, monkeypatch):
    """During shutdown, non-system paths should return 503."""
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "_shutting_down", True)
    resp = await client_with_cache.post(
        "/api/describe",
        json={"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]},
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert resp.status_code == 503
    monkeypatch.setattr(main_mod, "_shutting_down", False)


async def test_shutdown_middleware_allows_health(client_with_cache, monkeypatch):
    """During shutdown, health endpoint should still work."""
    import app.db.supabase as supabase_mod
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "_shutting_down", True)
    monkeypatch.setattr(supabase_mod, "ping", AsyncMock(return_value=True))
    resp = await client_with_cache.get("/api/health")
    # Health endpoint is allowed through shutdown middleware but returns 503 with shutting_down
    assert resp.status_code in (200, 503)
    assert resp.json()["status"] == "shutting_down"
    monkeypatch.setattr(main_mod, "_shutting_down", False)


class TestRequestIdValidation:
    @staticmethod
    async def _mock_ping():
        return True

    async def test_invalid_request_id_ignored(self, client_with_cache, monkeypatch):
        """Client-provided X-Request-ID with invalid chars is replaced."""
        import app.db.supabase as supabase_mod

        monkeypatch.setattr(supabase_mod, "ping", self._mock_ping)
        resp = await client_with_cache.get(
            "/api/health",
            headers={"X-Request-ID": "evil\nheader\r\ninjection"},
        )
        assert resp.status_code == 200
        rid = resp.headers["x-request-id"]
        assert rid != "evil\nheader\r\ninjection"
        assert len(rid) == 16

    async def test_overlong_request_id_ignored(self, client_with_cache, monkeypatch):
        """X-Request-ID longer than 128 chars is replaced with a generated one."""
        import app.db.supabase as supabase_mod

        monkeypatch.setattr(supabase_mod, "ping", self._mock_ping)
        resp = await client_with_cache.get(
            "/api/health",
            headers={"X-Request-ID": "a" * 200},
        )
        rid = resp.headers["x-request-id"]
        assert len(rid) == 16

    async def test_valid_custom_request_id_with_hyphens(self, client_with_cache, monkeypatch):
        """X-Request-ID with hyphens and underscores is accepted."""
        import app.db.supabase as supabase_mod

        monkeypatch.setattr(supabase_mod, "ping", self._mock_ping)
        custom_id = "req-123_abc-XYZ"
        resp = await client_with_cache.get(
            "/api/health",
            headers={"X-Request-ID": custom_id},
        )
        assert resp.headers["x-request-id"] == custom_id
