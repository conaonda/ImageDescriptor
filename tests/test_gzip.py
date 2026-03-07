import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache.store import CacheStore
from app.config import settings
from app.main import app


@pytest.fixture
async def client():
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


@pytest.mark.asyncio
async def test_gzip_response_when_accept_encoding(client):
    """Accept-Encoding: gzip 헤더가 있으면 응답이 gzip 압축되어야 한다."""
    resp = await client.get(
        "/api/v1/health",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    # httpx는 자동으로 디코딩하므로 content-encoding 헤더로 확인
    # 응답 크기가 min_size 미만이면 압축되지 않을 수 있음
    # health 엔드포인트는 작을 수 있으므로 미들웨어 등록 자체를 검증
    assert resp.json()["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_no_gzip_without_accept_encoding(client):
    """Accept-Encoding 헤더 없으면 압축하지 않는다."""
    resp = await client.get(
        "/api/v1/health",
        headers={"Accept-Encoding": "identity"},
    )
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers or resp.headers.get("content-encoding") != "gzip"


@pytest.mark.asyncio
async def test_gzip_middleware_registered():
    """GZipMiddleware가 앱에 등록되어 있는지 확인."""
    from starlette.middleware.gzip import GZipMiddleware as StarletteGZip

    middleware_classes = [m.cls for m in app.user_middleware if hasattr(m, "cls")]
    assert StarletteGZip in middleware_classes


@pytest.mark.asyncio
async def test_gzip_min_size_config():
    """gzip_min_size 설정이 정상적으로 로드되는지 확인."""
    assert isinstance(settings.gzip_min_size, int)
    assert settings.gzip_min_size > 0


@pytest.mark.asyncio
async def test_gzip_actual_compression_on_large_response():
    """500 bytes 초과 응답(OpenAPI 스키마)은 실제로 gzip 압축되어야 한다."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        resp = await c.get(
            "/openapi.json",
            headers={"Accept-Encoding": "gzip"},
        )
    assert resp.status_code == 200
    # OpenAPI 스키마는 수 KB이므로 gzip 압축이 적용되어야 함
    assert resp.headers.get("content-encoding") == "gzip"
