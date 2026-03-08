from unittest.mock import AsyncMock, patch

import pytest

from app.cache.store import CacheStore
from app.modules.geocoder import _round_coords, geocode


def test_round_coords():
    lon, lat = _round_coords(126.97823, 37.56612)
    assert lon == 126.978
    assert lat == 37.566


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


async def test_geocode_seoul(cache, httpx_mock):
    httpx_mock.add_response(
        url="https://nominatim.openstreetmap.org/reverse?lat=37.566&lon=126.978&format=jsonv2&accept-language=ko&zoom=8",
        json={
            "display_name": "중구, 서울특별시, 대한민국",
            "address": {
                "country": "대한민국",
                "country_code": "kr",
                "state": "서울특별시",
                "city": "중구",
            },
        },
    )

    result = await geocode(126.978, 37.566, cache)
    assert result.country == "대한민국"
    assert result.country_code == "kr"
    assert result.region == "서울특별시"


async def test_geocode_cache_hit(cache, httpx_mock):
    httpx_mock.add_response(
        json={
            "display_name": "Test",
            "address": {"country": "Test", "country_code": "xx", "state": "S"},
        }
    )

    await geocode(126.978, 37.566, cache)
    # Second call should hit cache, no additional HTTP request
    result = await geocode(126.978, 37.566, cache)
    assert result.country == "Test"
    assert len(httpx_mock.get_requests()) == 1


async def test_geocode_uses_settings_cache_ttl(cache, httpx_mock):
    """settings.cache_ttl_seconds가 geocoder의 cache.set()에 사용되어야 한다."""
    httpx_mock.add_response(
        json={
            "display_name": "서울",
            "address": {"country": "대한민국", "country_code": "kr", "state": "서울특별시"},
        }
    )

    from app.config import settings

    mock_set = AsyncMock()
    with patch.object(cache, "set", mock_set):
        await geocode(126.978, 37.566, cache)

    mock_set.assert_called_once()
    _, kwargs = mock_set.call_args
    assert "ttl_seconds" in kwargs, "cache.set()은 ttl_days 대신 ttl_seconds를 사용해야 합니다"
    assert kwargs["ttl_seconds"] == settings.cache_ttl_seconds, (
        f"cache_ttl_seconds({settings.cache_ttl_seconds})가 사용되어야 하지만 "
        f"ttl_seconds={kwargs.get('ttl_seconds')}가 전달되었습니다"
    )


async def test_geocode_invalid_json_response(cache, httpx_mock):
    """#239: 외부 API가 비정상 JSON을 반환하면 graceful fallback."""
    httpx_mock.add_response(
        url="https://nominatim.openstreetmap.org/reverse?lat=37.566&lon=126.978&format=jsonv2&accept-language=ko&zoom=8",
        text="<html>Error</html>",
        headers={"content-type": "text/html"},
    )

    result = await geocode(126.978, 37.566, cache)
    assert result.country == "Unknown"
    assert result.lat == 37.566
    assert result.lon == 126.978
