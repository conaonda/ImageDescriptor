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
        url="https://nominatim.openstreetmap.org/reverse?lat=37.566&lon=126.978&format=jsonv2&accept-language=ko&zoom=10",
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
