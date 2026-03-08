"""Tests for landcover cache write timeout (#269)."""

import asyncio
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


async def test_cache_write_timeout_does_not_hang(cache, httpx_mock):
    """cache.set()이 타임아웃되면 결과는 정상 반환하고 hang하지 않아야 한다."""
    httpx_mock.add_response(json={"elements": [{"tags": {"landuse": "residential"}}]})

    async def _slow_set(*args, **kwargs):
        await asyncio.sleep(100)

    with patch.object(cache, "set", side_effect=_slow_set):
        with patch("app.modules.landcover.settings") as mock_settings:
            mock_settings.overpass_url = "https://overpass-api.de/api/interpreter"
            mock_settings.timeout_landcover = 15.0
            mock_settings.overpass_timeout = 10
            mock_settings.cache_ttl_seconds = 86400 * 30
            mock_settings.cache_write_timeout = 0.01

            result = await get_land_cover(126.978, 37.566, cache)

    assert len(result.classes) == 1
    assert result.classes[0].type == "residential"


async def test_cache_write_success(cache, httpx_mock):
    """정상적인 cache.set()은 타임아웃 없이 완료되어야 한다."""
    httpx_mock.add_response(json={"elements": [{"tags": {"landuse": "forest"}}]})

    mock_set = AsyncMock()
    with patch.object(cache, "set", mock_set):
        result = await get_land_cover(10.0, 20.0, cache)

    mock_set.assert_called_once()
    assert result.classes[0].type == "forest"


async def test_cache_write_timeout_config_default():
    """cache_write_timeout 기본값이 설정되어 있어야 한다."""
    from app.config import Settings

    fields = Settings.model_fields
    assert "cache_write_timeout" in fields
    assert fields["cache_write_timeout"].default == 5.0
