import httpx
import pytest

from app.api.schemas import Mission
from app.cache.store import CacheStore
from app.modules.mission import (
    _guess_collection,
    _parse_mission,
    get_mission_metadata,
)

SAMPLE_STAC_RESPONSE = {
    "collection": "sentinel-2-c1-l2a",
    "properties": {
        "platform": "sentinel-2c",
        "instruments": ["msi"],
        "constellation": "sentinel-2",
        "eo:cloud_cover": 0.48,
        "gsd": 10,
        "eo:bands": [{"name": f"B{i}"} for i in range(13)],
        "s2:processing_level": "Level-2A",
    },
}


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


def test_guess_collection_l2a():
    assert _guess_collection("S2C_T52SCG_20260225T022315_L2A") == "sentinel-2-c1-l2a"


def test_guess_collection_l1c():
    assert _guess_collection("S2A_T52SCG_20260225T022315_L1C") == "sentinel-2-l1c"


def test_guess_collection_default():
    assert _guess_collection("UNKNOWN_ID") == "sentinel-2-c1-l2a"


def test_parse_mission_full():
    result = _parse_mission(SAMPLE_STAC_RESPONSE)
    assert result["platform"] == "sentinel-2c"
    assert result["instrument"] == "msi"
    assert result["constellation"] == "sentinel-2"
    assert result["processing_level"] == "L2A"
    assert result["cloud_cover"] == 0.48
    assert result["gsd"] == 10
    assert result["spectral_bands"] == 13


def test_parse_mission_empty_instruments():
    data = {
        "collection": "sentinel-2-c1-l2a",
        "properties": {"platform": "sentinel-2c", "instruments": []},
    }
    result = _parse_mission(data)
    assert result["instrument"] == "unknown"


def test_parse_mission_missing_instruments():
    data = {
        "collection": "sentinel-2-c1-l2a",
        "properties": {"platform": "sentinel-2c"},
    }
    result = _parse_mission(data)
    assert result["instrument"] == "unknown"


def test_parse_mission_processing_level_from_collection():
    data = {
        "collection": "sentinel-2-c1-l2a",
        "properties": {"platform": "sentinel-2c", "s2:product_type": "S2MSI2A"},
    }
    result = _parse_mission(data)
    assert result["processing_level"] == "L2A"


async def test_get_mission_metadata_none_stac_id(cache):
    result = await get_mission_metadata(None, cache)
    assert result is None


async def test_get_mission_metadata_success(cache, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_STAC_RESPONSE)
    result = await get_mission_metadata("S2C_T52SCG_20260225T022315_L2A", cache)
    assert isinstance(result, Mission)
    assert result.platform == "sentinel-2c"
    assert result.instrument == "msi"
    assert result.cloud_cover == 0.48


async def test_get_mission_metadata_cache_hit(cache, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_STAC_RESPONSE)
    stac_id = "S2C_T52SCG_20260225T022315_L2A"

    await get_mission_metadata(stac_id, cache)
    result = await get_mission_metadata(stac_id, cache)

    assert result.platform == "sentinel-2c"
    assert len(httpx_mock.get_requests()) == 1


async def test_get_mission_metadata_http_error(cache, httpx_mock):
    httpx_mock.add_response(status_code=404)
    with pytest.raises(httpx.HTTPStatusError):
        await get_mission_metadata("INVALID_ID", cache)
