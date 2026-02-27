from unittest.mock import AsyncMock, patch

import pytest

from app.api.schemas import Context, DescribeRequest, Event, LandCover, LandCoverClass, Location
from app.cache.store import CacheStore
from app.services.composer import compose_description


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


def _make_request():
    return DescribeRequest(
        thumbnail="dGVzdA==",
        coordinates=[126.978, 37.566],
        captured_at="2025-06-15T00:00:00Z",
    )


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_all_success(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    mock_geo.geocode = AsyncMock(
        return_value=Location(
            country="대한민국",
            country_code="kr",
            region="서울",
            city="중구",
            place_name="서울특별시",
            lat=37.566,
            lon=126.978,
        )
    )
    mock_lc.get_land_cover = AsyncMock(
        return_value=LandCover(
            classes=[LandCoverClass(type="residential", label="주거지역", percentage=60)],
            summary="주거지역 60%",
        )
    )
    mock_desc.describe_image = AsyncMock(return_value="위성영상 설명입니다.")
    mock_ctx.research_context = AsyncMock(
        return_value=Context(
            events=[
                Event(
                    title="이벤트",
                    date="2025-06",
                    source_url="https://example.com",
                    relevance="medium",
                )
            ],
            summary="이벤트 요약",
        )
    )

    result = await compose_description(_make_request(), cache)

    assert result.description == "위성영상 설명입니다."
    assert result.location.country == "대한민국"
    assert len(result.land_cover.classes) == 1
    assert len(result.context.events) == 1
    assert len(result.warnings) == 0


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_partial_failure(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """Nominatim 장애 시 점진적 실패 테스트."""
    mock_geo.geocode = AsyncMock(side_effect=Exception("Nominatim timeout"))
    mock_lc.get_land_cover = AsyncMock(
        return_value=LandCover(
            classes=[],
            summary="정보 없음",
        )
    )
    mock_desc.describe_image = AsyncMock(return_value="설명 텍스트")
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    result = await compose_description(_make_request(), cache)

    assert result.location is None
    assert result.description == "설명 텍스트"
    assert len(result.warnings) == 1
    assert result.warnings[0].module == "geocoder"


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_all_fail(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    mock_geo.geocode = AsyncMock(side_effect=Exception("fail"))
    mock_lc.get_land_cover = AsyncMock(side_effect=Exception("fail"))
    mock_desc.describe_image = AsyncMock(side_effect=Exception("fail"))
    mock_ctx.research_context = AsyncMock(side_effect=Exception("fail"))

    result = await compose_description(_make_request(), cache)

    assert result.description is None
    assert result.location is None
    assert result.land_cover is None
    assert result.context is None
    assert len(result.warnings) == 4
