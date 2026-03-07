"""API 입력 검증 및 보안 네거티브 테스트.

OWASP 기본 체크리스트 기반으로 비정상 입력에 대한 방어를 검증합니다.
closes #178
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.config import settings
from app.main import app


@pytest.fixture
async def client():
    """인증된 클라이언트."""
    cache = CacheStore(settings.cache_db_path)
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


@pytest.fixture
async def unauth_client():
    """인증 없는 클라이언트."""
    cache = CacheStore(settings.cache_db_path)
    await cache.init()
    app.state.cache = cache

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    await cache.close()


# ──────────────────────────────────────────────
# 1. 비정상 좌표값 검증
# ──────────────────────────────────────────────


class TestInvalidCoordinates:
    """좌표 범위 초과 및 타입 오류 테스트."""

    @pytest.mark.asyncio
    async def test_longitude_out_of_range(self, client):
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [200.0, 37.0]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_latitude_out_of_range(self, client):
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 100.0]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_overflow_coordinates(self, client):
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [-181.0, -91.0]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_coordinates_wrong_type_string(self, client):
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": ["abc", "def"]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_coordinates_too_few_elements(self, client):
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_coordinates_too_many_elements(self, client):
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0, 0.0]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_coordinates_null(self, client):
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": None},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_coordinates_nan_infinity(self, client):
        """NaN/Infinity는 JSON 표준이 아니므로 문자열로 전달 시 422."""
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": ["NaN", "Infinity"]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_bbox(self, client):
        """bbox에서 west >= east인 경우 422."""
        resp = await client.post(
            "/api/v1/describe",
            json={
                "thumbnail": "https://example.com/img.jpg",
                "coordinates": [126.0, 37.0],
                "bbox": [127.0, 37.0, 126.0, 38.0],  # west > east
            },
        )
        assert resp.status_code == 422


# ──────────────────────────────────────────────
# 2. 과도하게 긴 입력값 처리
# ──────────────────────────────────────────────


class TestOversizedInput:
    """과도하게 큰 입력 검증."""

    @pytest.mark.asyncio
    async def test_thumbnail_too_large(self, client):
        """5MB 초과 thumbnail은 422."""
        large_thumbnail = "A" * (5 * 1024 * 1024 + 1)
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": large_thumbnail, "coordinates": [126.0, 37.0]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_batch_exceeds_max_size(self, client):
        """배치 요청이 MAX_BATCH_SIZE(10)을 초과하면 422."""
        items = [
            {"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]}
            for _ in range(11)
        ]
        resp = await client.post("/api/v1/describe/batch", json={"items": items})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_batch(self, client):
        """빈 배치 요청은 422."""
        resp = await client.post("/api/v1/describe/batch", json={"items": []})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_very_long_cog_image_id(self, client):
        """매우 긴 cog_image_id는 정상 처리되어야 하지만 404."""
        long_id = "x" * 10000
        resp = await client.get(f"/api/v1/descriptions/{long_id}")
        # 유효한 요청이지만 존재하지 않으므로 404
        assert resp.status_code == 404


# ──────────────────────────────────────────────
# 3. 잘못된 Content-Type 요청
# ──────────────────────────────────────────────


class TestInvalidContentType:
    """잘못된 Content-Type 요청 처리."""

    @pytest.mark.asyncio
    async def test_plain_text_body(self, client):
        """Content-Type: text/plain으로 POST하면 422."""
        resp = await client.post(
            "/api/v1/describe",
            content="not json",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_form_urlencoded(self, client):
        """Content-Type: application/x-www-form-urlencoded으로 POST하면 422."""
        resp = await client.post(
            "/api/v1/describe",
            content="thumbnail=abc&coordinates=126,37",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_malformed_json(self, client):
        """깨진 JSON은 422."""
        resp = await client.post(
            "/api/v1/describe",
            content="{broken json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_body(self, client):
        """빈 body는 422."""
        resp = await client.post(
            "/api/v1/describe",
            content="",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422


# ──────────────────────────────────────────────
# 4. 인증 우회 시도
# ──────────────────────────────────────────────


class TestAuthBypass:
    """인증 우회 시도 테스트."""

    @pytest.mark.asyncio
    async def test_no_auth_header(self, unauth_client):
        """인증 헤더 없이 요청하면 401."""
        resp = await unauth_client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_api_key(self, unauth_client):
        """잘못된 API 키는 401."""
        resp = await unauth_client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]},
            headers={"X-API-Key": "wrong-key-12345"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_api_key(self, unauth_client):
        """빈 API 키는 401."""
        resp = await unauth_client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]},
            headers={"X-API-Key": ""},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_bearer_token(self, unauth_client):
        """잘못된 Bearer 토큰은 401."""
        from unittest.mock import AsyncMock, patch

        fake_jwks = {"keys": []}
        with patch("app.auth._get_jwks", new_callable=AsyncMock, return_value=fake_jwks):
            resp = await unauth_client.post(
                "/api/v1/describe",
                json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]},
                headers={"Authorization": "Bearer invalid.token.here"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_auth_on_batch(self, unauth_client):
        """배치 엔드포인트도 인증 필요."""
        resp = await unauth_client.post(
            "/api/v1/describe/batch",
            json={
                "items": [
                    {"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]}
                ]
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_auth_on_descriptions(self, unauth_client):
        """descriptions 엔드포인트도 인증 필요."""
        resp = await unauth_client.get("/api/v1/descriptions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_auth_on_geocode(self, unauth_client):
        """geocode 엔드포인트도 인증 필요."""
        resp = await unauth_client.post(
            "/api/v1/geocode",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, unauth_client):
        """health 엔드포인트는 인증 불필요."""
        resp = await unauth_client.get("/api/v1/health")
        assert resp.status_code == 200


# ──────────────────────────────────────────────
# 5. 응답 형식 검증 (RFC 9457 Problem Details)
# ──────────────────────────────────────────────


class TestErrorResponseFormat:
    """에러 응답이 RFC 9457 Problem Details 형식인지 검증."""

    @pytest.mark.asyncio
    async def test_validation_error_format(self, client):
        """422 에러가 problem+json 형식으로 반환되는지 확인."""
        resp = await client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [999, 999]},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "title" in body
        assert "status" in body
        assert body["status"] == 422

    @pytest.mark.asyncio
    async def test_401_error_format(self, unauth_client):
        """401 에러가 problem+json 형식으로 반환되는지 확인."""
        resp = await unauth_client.post(
            "/api/v1/describe",
            json={"thumbnail": "https://example.com/img.jpg", "coordinates": [126.0, 37.0]},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "title" in body
        assert "status" in body
        assert body["status"] == 401


# ──────────────────────────────────────────────
# 6. 보안 헤더 검증
# ──────────────────────────────────────────────


class TestSecurityHeaders:
    """보안 응답 헤더가 올바르게 설정되는지 검증."""

    @pytest.mark.asyncio
    async def test_security_headers_present(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "strict-transport-security" in resp.headers
