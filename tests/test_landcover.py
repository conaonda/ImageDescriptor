from unittest.mock import AsyncMock, patch

import pytest

from app.cache.store import CacheStore
from app.modules.landcover import get_land_cover


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


async def test_land_cover_residential(cache, httpx_mock):
    httpx_mock.add_response(
        json={
            "elements": [
                {"tags": {"landuse": "residential"}},
                {"tags": {"landuse": "residential"}},
                {"tags": {"landuse": "commercial"}},
                {"tags": {"natural": "forest"}},
            ]
        }
    )

    result = await get_land_cover(126.978, 37.566, cache)
    assert len(result.classes) == 3
    assert result.classes[0].type == "residential"
    assert result.classes[0].label == "주거지역"
    assert result.classes[0].percentage == 50


async def test_land_cover_empty(cache, httpx_mock):
    httpx_mock.add_response(json={"elements": []})

    result = await get_land_cover(0.0, 0.0, cache)
    assert len(result.classes) == 0
    assert result.summary == "정보 없음"


async def test_landcover_uses_settings_cache_ttl(cache, httpx_mock):
    """settings.cache_ttl_seconds가 landcover의 cache.set()에 사용되어야 한다."""
    httpx_mock.add_response(json={"elements": [{"tags": {"landuse": "residential"}}]})

    from app.config import settings

    mock_set = AsyncMock()
    with patch.object(cache, "set", mock_set):
        await get_land_cover(126.978, 37.566, cache)

    mock_set.assert_called_once()
    _, kwargs = mock_set.call_args
    assert "ttl_seconds" in kwargs, "cache.set()은 ttl_days 대신 ttl_seconds를 사용해야 합니다"
    assert kwargs["ttl_seconds"] == settings.cache_ttl_seconds, (
        f"cache_ttl_seconds({settings.cache_ttl_seconds})가 사용되어야 하지만 "
        f"ttl_seconds={kwargs.get('ttl_seconds')}가 전달되었습니다"
    )


async def test_land_cover_invalid_json_response(cache, httpx_mock):
    """#239: 외부 API가 비정상 JSON을 반환하면 graceful fallback."""
    httpx_mock.add_response(
        text="<html>502 Bad Gateway</html>",
        headers={"content-type": "text/html"},
    )

    result = await get_land_cover(126.978, 37.566, cache)
    assert len(result.classes) == 0
    assert result.summary == "정보 없음"
