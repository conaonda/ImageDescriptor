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
    httpx_mock.add_response(json={
        "elements": [
            {"tags": {"landuse": "residential"}},
            {"tags": {"landuse": "residential"}},
            {"tags": {"landuse": "commercial"}},
            {"tags": {"natural": "forest"}},
        ]
    })

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
