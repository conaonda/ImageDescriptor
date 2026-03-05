from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.api.schemas import Mission
from app.cache.store import CacheStore
from app.modules.mission import _parse_stac_item, get_mission_metadata


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


SAMPLE_STAC_RESPONSE = {
    "type": "Feature",
    "id": "S2C_T52SCG_20260225T022315_L2A",
    "properties": {
        "platform": "Sentinel-2C",
        "instruments": ["msi"],
        "constellation": "Sentinel-2",
        "processing:level": "L2A",
        "eo:cloud_cover": 0.48,
        "gsd": 10.0,
        "datetime": "2026-02-25T02:23:15Z",
        "s2:datatake_type": "INS-NOBS",
        "view:sun_elevation": 35.2,
    },
}


class TestParseStacItem:
    def test_parse_full_response(self):
        result = _parse_stac_item(SAMPLE_STAC_RESPONSE)
        assert result.platform == "Sentinel-2C"
        assert result.instrument == "msi"
        assert result.constellation == "Sentinel-2"
        assert result.processing_level == "L2A"
        assert result.cloud_cover == 0.48
        assert result.gsd == 10.0
        assert result.spectral_bands == 13

    def test_parse_missing_optional_fields(self):
        data = {"properties": {"platform": "Sentinel-2A", "instruments": ["msi"]}}
        result = _parse_stac_item(data)
        assert result.platform == "Sentinel-2A"
        assert result.constellation is None
        assert result.processing_level is None
        assert result.cloud_cover is None

    def test_parse_empty_properties(self):
        result = _parse_stac_item({"properties": {}})
        assert result.platform == "unknown"
        assert result.instrument == "unknown"

    def test_parse_multiple_instruments(self):
        data = {"properties": {"platform": "test", "instruments": ["msi", "olci"]}}
        result = _parse_stac_item(data)
        assert result.instrument == "msi,olci"


class TestGetMissionMetadata:
    async def test_returns_none_for_empty_stac_id(self, cache):
        result = await get_mission_metadata("", cache)
        assert result is None

    async def test_returns_none_for_none_stac_id(self, cache):
        result = await get_mission_metadata(None, cache)
        assert result is None

    @patch("app.modules.mission._fetch_stac_item")
    async def test_fetches_and_caches(self, mock_fetch, cache):
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.json.return_value = SAMPLE_STAC_RESPONSE
        mock_fetch.return_value = mock_resp

        stac_id = "S2C_T52SCG_20260225T022315_L2A"
        result = await get_mission_metadata(stac_id, cache)

        assert result.platform == "Sentinel-2C"
        assert result.cloud_cover == 0.48
        mock_fetch.assert_called_once_with(stac_id)

        # Second call should use cache
        mock_fetch.reset_mock()
        result2 = await get_mission_metadata(stac_id, cache)
        assert result2.platform == "Sentinel-2C"
        mock_fetch.assert_not_called()

    @patch("app.modules.mission._fetch_stac_item")
    async def test_cache_miss_then_hit(self, mock_fetch, cache):
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.json.return_value = SAMPLE_STAC_RESPONSE
        mock_fetch.return_value = mock_resp

        stac_id = "S2C_TEST_ID"
        await get_mission_metadata(stac_id, cache)

        # Verify cache was populated
        cached = await cache.get(f"mission:{stac_id}")
        assert cached is not None
        assert cached["platform"] == "Sentinel-2C"

    @patch("app.modules.mission._fetch_stac_item")
    async def test_network_error_propagates(self, mock_fetch, cache):
        mock_fetch.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            await get_mission_metadata("bad-id", cache)

    @patch("app.modules.mission._fetch_stac_item")
    async def test_http_404_propagates(self, mock_fetch, cache):
        mock_fetch.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("GET", "http://test"),
            response=httpx.Response(404),
        )

        with pytest.raises(httpx.HTTPStatusError):
            await get_mission_metadata("nonexistent-id", cache)


class TestMissionInComposer:
    """Test mission module integration in composer."""

    @patch("app.services.composer.mission")
    @patch("app.services.composer.context")
    @patch("app.services.composer.describer")
    @patch("app.services.composer.landcover")
    @patch("app.services.composer.geocoder")
    async def test_compose_with_stac_id(
        self, mock_geo, mock_lc, mock_desc, mock_ctx, mock_mission, cache
    ):
        from app.api.schemas import (
            Context,
            DescribeRequest,
            LandCover,
            LandCoverClass,
            Location,
        )
        from app.services.composer import compose_description

        mock_geo.geocode = AsyncMock(
            return_value=Location(
                country="대한민국", country_code="kr", region="서울",
                city="중구", place_name="서울특별시", lat=37.566, lon=126.978,
            )
        )
        mock_lc.get_land_cover = AsyncMock(
            return_value=LandCover(
                classes=[LandCoverClass(type="residential", label="주거지역", percentage=60)],
                summary="주거지역 60%",
            )
        )
        mock_desc.describe_image = AsyncMock(return_value="설명")
        mock_ctx.research_context = AsyncMock(
            return_value=Context(events=[], summary="없음")
        )
        mock_mission.get_mission_metadata = AsyncMock(
            return_value=Mission(
                platform="Sentinel-2C", instrument="msi",
                constellation="Sentinel-2", processing_level="L2A",
                cloud_cover=0.48, gsd=10.0, spectral_bands=13,
            )
        )

        request = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
            captured_at="2025-06-15T00:00:00Z",
            stac_id="S2C_T52SCG_20260225T022315_L2A",
        )
        result = await compose_description(request, cache)

        assert result.mission is not None
        assert result.mission.platform == "Sentinel-2C"
        assert result.mission.cloud_cover == 0.48
        mock_mission.get_mission_metadata.assert_called_once()

    @patch("app.services.composer.mission")
    @patch("app.services.composer.context")
    @patch("app.services.composer.describer")
    @patch("app.services.composer.landcover")
    @patch("app.services.composer.geocoder")
    async def test_compose_without_stac_id(
        self, mock_geo, mock_lc, mock_desc, mock_ctx, mock_mission, cache
    ):
        from app.api.schemas import Context, DescribeRequest, LandCover, Location
        from app.services.composer import compose_description

        mock_geo.geocode = AsyncMock(
            return_value=Location(
                country="대한민국", country_code="kr", region="서울",
                city="중구", place_name="서울특별시", lat=37.566, lon=126.978,
            )
        )
        mock_lc.get_land_cover = AsyncMock(
            return_value=LandCover(classes=[], summary="정보 없음")
        )
        mock_desc.describe_image = AsyncMock(return_value="설명")
        mock_ctx.research_context = AsyncMock(
            return_value=Context(events=[], summary="없음")
        )

        request = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
        )
        result = await compose_description(request, cache)

        assert result.mission is None
        mock_mission.get_mission_metadata.assert_not_called()

    @patch("app.services.composer.mission")
    @patch("app.services.composer.context")
    @patch("app.services.composer.describer")
    @patch("app.services.composer.landcover")
    @patch("app.services.composer.geocoder")
    async def test_compose_mission_failure_graceful(
        self, mock_geo, mock_lc, mock_desc, mock_ctx, mock_mission, cache
    ):
        from app.api.schemas import Context, DescribeRequest, LandCover, Location
        from app.services.composer import compose_description

        mock_geo.geocode = AsyncMock(
            return_value=Location(
                country="대한민국", country_code="kr", region="서울",
                city="중구", place_name="서울특별시", lat=37.566, lon=126.978,
            )
        )
        mock_lc.get_land_cover = AsyncMock(
            return_value=LandCover(classes=[], summary="정보 없음")
        )
        mock_desc.describe_image = AsyncMock(return_value="설명")
        mock_ctx.research_context = AsyncMock(
            return_value=Context(events=[], summary="없음")
        )
        mock_mission.get_mission_metadata = AsyncMock(
            side_effect=Exception("STAC API down")
        )

        request = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
            stac_id="bad-id",
        )
        result = await compose_description(request, cache)

        assert result.mission is None
        assert result.description == "설명"
        assert any(w.module == "mission" for w in result.warnings)
