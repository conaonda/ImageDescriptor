"""v1 API 엔드포인트 통합 테스트.

describe → list → get → delete 전체 워크플로우와
Rate Limiting 헤더 검증, 인증 흐름을 통합 테스트합니다.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import limiter as routes_limiter
from app.cache.store import CacheStore
from app.main import app, limiter


@pytest.fixture
async def integration_client(tmp_path):
    cache = CacheStore(str(tmp_path / "integration.db"))
    await cache.init()
    app.state.cache = cache
    limiter.reset()
    routes_limiter.reset()
    api_key = os.environ["API_KEY"]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as c:
        yield c
    limiter.reset()
    routes_limiter.reset()
    await cache.close()


class TestV1WorkflowIntegration:
    """describe → list → get → delete 전체 흐름 통합 테스트."""

    async def test_full_crud_workflow(self, integration_client, monkeypatch):
        """describe로 생성 → list로 확인 → get으로 조회 → delete로 삭제하는 전체 흐름."""
        import app.db.supabase as db_mod
        from app.api.schemas import DescribeResponse, Location

        cog_id = "integration-test-img-001"

        # 1. describe: 분석 결과 생성 및 저장
        mock_result = DescribeResponse(
            description="통합 테스트 설명",
            location=Location(
                country="대한민국",
                country_code="kr",
                region="서울",
                city="서울",
                place_name="서울, 대한민국",
                lat=37.566,
                lon=126.978,
            ),
            saved=True,
        )
        monkeypatch.setattr(
            "app.api.routes._describe_and_save",
            AsyncMock(return_value=mock_result),
        )

        resp = await integration_client.post(
            "/api/v1/describe",
            json={
                "thumbnail": "dGVzdA==",
                "coordinates": [126.978, 37.566],
                "captured_at": "2025-06-15T00:00:00Z",
                "cog_image_id": cog_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "통합 테스트 설명"
        assert data["saved"] is True

        # 2. list: 저장된 설명 목록 조회
        mock_list = {
            "items": [{"cog_image_id": cog_id, "description": "통합 테스트 설명"}],
            "total": 1,
        }
        monkeypatch.setattr(db_mod, "list_descriptions", AsyncMock(return_value=mock_list))

        resp = await integration_client.get("/api/v1/descriptions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(item["cog_image_id"] == cog_id for item in data["items"])

        # 3. get: 개별 설명 조회
        mock_detail = {"cog_image_id": cog_id, "description": "통합 테스트 설명"}
        monkeypatch.setattr(db_mod, "get_description", AsyncMock(return_value=mock_detail))

        resp = await integration_client.get(f"/api/v1/descriptions/{cog_id}")
        assert resp.status_code == 200
        assert resp.json()["cog_image_id"] == cog_id

        # 4. delete: 설명 삭제
        monkeypatch.setattr(db_mod, "delete_description", AsyncMock(return_value=True))

        resp = await integration_client.delete(f"/api/v1/descriptions/{cog_id}")
        assert resp.status_code == 204

        # 5. get after delete: 삭제 후 조회 시 404
        monkeypatch.setattr(db_mod, "get_description", AsyncMock(return_value=None))

        resp = await integration_client.get(f"/api/v1/descriptions/{cog_id}")
        assert resp.status_code == 404

    async def test_describe_then_list_with_filters(self, integration_client, monkeypatch):
        """describe 후 created_after/created_before 필터로 list 조회."""
        import app.db.supabase as db_mod
        from app.api.schemas import DescribeResponse

        mock_result = DescribeResponse(description="필터 테스트")
        monkeypatch.setattr(
            "app.api.routes._describe_and_save",
            AsyncMock(return_value=mock_result),
        )

        resp = await integration_client.post(
            "/api/v1/describe",
            json={"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]},
        )
        assert resp.status_code == 200

        mock_list = {"items": [], "total": 0}
        monkeypatch.setattr(db_mod, "list_descriptions", AsyncMock(return_value=mock_list))

        resp = await integration_client.get(
            "/api/v1/descriptions?created_after=2099-01-01T00:00:00Z"
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestV1RateLimitHeaders:
    """Rate Limiting 헤더 검증 통합 테스트."""

    async def test_rate_limit_headers_on_describe(self, integration_client, monkeypatch):
        """describe 엔드포인트에서 rate limit 초과 시 RFC 7807 + Retry-After 헤더."""
        from app.api.schemas import DescribeResponse

        mock_result = DescribeResponse(description="rate limit test")
        monkeypatch.setattr(
            "app.api.routes._describe_and_save",
            AsyncMock(return_value=mock_result),
        )

        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }

        with patch("app.config.settings.rate_limit_describe", "1/minute"):
            resp1 = await integration_client.post("/api/v1/describe", json=body)
            assert resp1.status_code == 200

            resp2 = await integration_client.post("/api/v1/describe", json=body)
            assert resp2.status_code == 429
            data = resp2.json()
            assert data["type"] == "https://problems.cognito-descriptor.io/rate-limit-exceeded"
            assert data["status"] == 429
            assert "Retry-After" in resp2.headers
            assert int(resp2.headers["Retry-After"]) > 0
            assert resp2.headers["content-type"] == "application/problem+json"

    async def test_rate_limit_on_read_endpoints(self, integration_client, monkeypatch):
        """descriptions 조회 엔드포인트에서 rate limit 초과 시 429."""
        import app.db.supabase as db_mod

        mock_list = {"items": [], "total": 0}
        monkeypatch.setattr(db_mod, "list_descriptions", AsyncMock(return_value=mock_list))

        with patch("app.config.settings.rate_limit_read", "1/minute"):
            resp1 = await integration_client.get("/api/v1/descriptions")
            assert resp1.status_code == 200

            resp2 = await integration_client.get("/api/v1/descriptions")
            assert resp2.status_code == 429
            assert "Retry-After" in resp2.headers

    async def test_rate_limit_on_data_endpoints(self, tmp_path):
        """data 엔드포인트(geocode)에서 rate limit 초과 시 429."""
        cache = CacheStore(str(tmp_path / "rl_data.db"))
        await cache.init()
        app.state.cache = cache
        limiter.reset()
        routes_limiter.reset()

        mock_geo = {
            "country": "대한민국",
            "country_code": "kr",
            "region": "서울",
            "city": "서울",
            "place_name": "서울",
            "lat": 37.5,
            "lon": 127.0,
        }
        api_key = os.environ["API_KEY"]

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-API-Key": api_key},
            ) as c:
                with (
                    patch("app.config.settings.rate_limit_data", "1/minute"),
                    patch(
                        "app.modules.geocoder.geocode",
                        new_callable=AsyncMock,
                        return_value=mock_geo,
                    ),
                ):
                    body = {"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]}

                    resp1 = await c.post("/api/v1/geocode", json=body)
                    assert resp1.status_code == 200

                    resp2 = await c.post("/api/v1/geocode", json=body)
                    assert resp2.status_code == 429
        finally:
            limiter.reset()
            routes_limiter.reset()
            await cache.close()

    async def test_independent_rate_limits_across_categories(self, tmp_path):
        """describe, data, read 엔드포인트가 각각 독립적인 rate limit을 가짐."""
        import app.db.supabase as db_mod
        from app.api.schemas import DescribeResponse

        cache = CacheStore(str(tmp_path / "rl_indep.db"))
        await cache.init()
        app.state.cache = cache
        limiter.reset()
        routes_limiter.reset()

        mock_result = DescribeResponse(description="test")
        mock_list = {"items": [], "total": 0}
        mock_geo = {
            "country": "KR",
            "country_code": "kr",
            "region": "Seoul",
            "city": "Seoul",
            "place_name": "Seoul",
            "lat": 37.5,
            "lon": 127.0,
        }
        api_key = os.environ["API_KEY"]

        body = {
            "thumbnail": "dGVzdA==",
            "coordinates": [126.978, 37.566],
            "captured_at": "2025-06-15T00:00:00Z",
        }

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-API-Key": api_key},
            ) as c:
                with (
                    patch("app.config.settings.rate_limit_describe", "1/minute"),
                    patch("app.config.settings.rate_limit_data", "1/minute"),
                    patch("app.config.settings.rate_limit_read", "1/minute"),
                    patch(
                        "app.api.routes._describe_and_save",
                        new_callable=AsyncMock,
                        return_value=mock_result,
                    ),
                    patch(
                        "app.modules.geocoder.geocode",
                        new_callable=AsyncMock,
                        return_value=mock_geo,
                    ),
                    patch.object(
                        db_mod,
                        "list_descriptions",
                        new_callable=AsyncMock,
                        return_value=mock_list,
                    ),
                ):
                    # Exhaust describe limit
                    await c.post("/api/v1/describe", json=body)
                    resp = await c.post("/api/v1/describe", json=body)
                    assert resp.status_code == 429

                    # data endpoint should still work
                    resp = await c.post("/api/v1/geocode", json=body)
                    assert resp.status_code == 200

                    # read endpoint should still work
                    resp = await c.get("/api/v1/descriptions")
                    assert resp.status_code == 200
        finally:
            limiter.reset()
            routes_limiter.reset()
            await cache.close()


class TestV1AuthIntegration:
    """인증 흐름 포함 통합 시나리오 테스트."""

    async def test_unauthenticated_requests_rejected(self, tmp_path):
        """인증 없이 모든 보호된 엔드포인트에 접근 시 401."""
        cache = CacheStore(str(tmp_path / "auth.db"))
        await cache.init()
        app.state.cache = cache

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            endpoints = [
                ("POST", "/api/v1/describe"),
                ("POST", "/api/v1/describe/batch"),
                ("POST", "/api/v1/geocode"),
                ("POST", "/api/v1/landcover"),
                ("POST", "/api/v1/context"),
                ("GET", "/api/v1/descriptions"),
                ("GET", "/api/v1/descriptions/some-id"),
                ("DELETE", "/api/v1/descriptions/some-id"),
            ]
            for method, path in endpoints:
                body = {"thumbnail": "dGVzdA==", "coordinates": [126.978, 37.566]}
                if method == "POST":
                    resp = await c.post(path, json=body)
                elif method == "GET":
                    resp = await c.get(path)
                else:
                    resp = await c.delete(path)
                assert resp.status_code == 401, (
                    f"{method} {path} should return 401, got {resp.status_code}"
                )

        await cache.close()

    async def test_system_endpoints_no_auth_required(self, integration_client, monkeypatch):
        """system 엔드포인트(health, cache/stats, circuits)는 인증 불필요."""
        import app.db.supabase as supabase_mod

        monkeypatch.setattr(supabase_mod, "ping", AsyncMock(return_value=True))

        # Remove auth header for this test
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            resp = await c.get("/api/v1/health")
            assert resp.status_code == 200

            resp = await c.get("/api/v1/cache/stats")
            assert resp.status_code == 200

            resp = await c.get("/api/v1/circuits")
            assert resp.status_code == 200

    async def test_security_headers_present(self, integration_client, monkeypatch):
        """모든 응답에 보안 헤더가 포함되어야 함."""
        import app.db.supabase as supabase_mod

        monkeypatch.setattr(supabase_mod, "ping", AsyncMock(return_value=True))

        resp = await integration_client.get("/api/v1/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert "strict-origin" in resp.headers["referrer-policy"]

    async def test_request_id_propagated(self, integration_client, monkeypatch):
        """X-Request-ID가 요청/응답 간 전파됨."""
        import app.db.supabase as supabase_mod

        monkeypatch.setattr(supabase_mod, "ping", AsyncMock(return_value=True))

        custom_id = "integration-test-req-123"
        resp = await integration_client.get(
            "/api/v1/health",
            headers={"X-Request-ID": custom_id},
        )
        assert resp.headers["x-request-id"] == custom_id


class TestV1LegacyRedirect:
    """Legacy redirect와 v1 엔드포인트 연동 통합 테스트."""

    async def test_legacy_redirect_chain(self, integration_client, monkeypatch):
        """legacy /api/health → 307 redirect → /api/v1/health."""
        import app.db.supabase as supabase_mod

        monkeypatch.setattr(supabase_mod, "ping", AsyncMock(return_value=True))

        # Without follow_redirects, verify redirect
        resp = await integration_client.get("/api/health")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/api/v1/health"
