from unittest.mock import AsyncMock, patch

import pytest
import structlog.testing

from app.api.schemas import Context, DescribeRequest, Event, LandCover, LandCoverClass, Location
from app.cache.store import CacheStore
from app.services.composer import _breakers, compose_description


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


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_circuit_breaker_open(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """Circuit breaker가 열려있을 때 경고 반환 및 모듈 호출 생략 테스트."""
    mock_geo.geocode = AsyncMock(return_value=None)
    mock_lc.get_land_cover = AsyncMock(return_value=None)
    mock_desc.describe_image = AsyncMock(return_value=None)
    mock_ctx.research_context = AsyncMock(return_value=None)

    # geocoder circuit breaker를 강제로 열기
    _breakers["geocoder"]._open_until = float("inf")

    try:
        result = await compose_description(_make_request(), cache)

        assert result.location is None
        assert len(result.warnings) == 1
        assert result.warnings[0].module == "geocoder"
        assert "Circuit breaker open" in result.warnings[0].error
    finally:
        # 테스트 격리를 위해 breaker 상태 복원
        _breakers["geocoder"]._open_until = 0.0
        _breakers["geocoder"]._failure_count = 0


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_landcover_fail_geocoder_ok(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """Phase 1에서 landcover만 실패해도 Phase 2가 정상 동작하는지 검증."""
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
    mock_lc.get_land_cover = AsyncMock(side_effect=Exception("LandCover API error"))
    mock_desc.describe_image = AsyncMock(return_value="설명 텍스트")
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    result = await compose_description(_make_request(), cache)

    assert result.location is not None
    assert result.location.place_name == "서울특별시"
    assert result.land_cover is None
    assert result.description == "설명 텍스트"
    assert len(result.warnings) == 1
    assert result.warnings[0].module == "landcover"


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_phase1_both_fail_phase2_uses_fallback(
    mock_geo, mock_lc, mock_desc, mock_ctx, cache
):
    """Phase 1 양쪽 실패 시 Phase 2가 fallback 값으로 동작하는지 검증."""
    mock_geo.geocode = AsyncMock(side_effect=Exception("fail"))
    mock_lc.get_land_cover = AsyncMock(side_effect=Exception("fail"))
    mock_desc.describe_image = AsyncMock(return_value="fallback 설명")
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    result = await compose_description(_make_request(), cache)

    assert result.location is None
    assert result.land_cover is None
    assert result.description == "fallback 설명"
    assert len(result.warnings) == 2
    # describer에는 fallback place_name "37.566, 126.978"과 lc_summary "정보 없음"이 전달됨
    mock_desc.describe_image.assert_called_once()
    call_args = mock_desc.describe_image.call_args
    assert call_args[0][1] == "37.566, 126.978"  # place_name fallback
    assert call_args[0][3] == "정보 없음"  # lc_summary fallback


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_multiple_circuit_breakers_open(
    mock_geo, mock_lc, mock_desc, mock_ctx, cache
):
    """여러 circuit breaker가 열려있을 때 모두 warning에 포함되는지 검증."""
    mock_geo.geocode = AsyncMock(return_value=None)
    mock_lc.get_land_cover = AsyncMock(return_value=None)
    mock_desc.describe_image = AsyncMock(return_value=None)
    mock_ctx.research_context = AsyncMock(return_value=None)

    _breakers["geocoder"]._open_until = float("inf")
    _breakers["landcover"]._open_until = float("inf")
    _breakers["describer"]._open_until = float("inf")

    try:
        result = await compose_description(_make_request(), cache)

        assert result.description is None
        assert result.location is None
        assert result.land_cover is None
        warning_modules = {w.module for w in result.warnings}
        assert "geocoder" in warning_modules
        assert "landcover" in warning_modules
        assert "describer" in warning_modules
        for w in result.warnings:
            if w.module in ("geocoder", "landcover", "describer"):
                assert "Circuit breaker open" in w.error
    finally:
        for name in ("geocoder", "landcover", "describer"):
            _breakers[name]._open_until = 0.0
            _breakers[name]._failure_count = 0


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_without_captured_at(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """captured_at 없이 요청해도 정상 동작하는지 검증."""
    request = DescribeRequest(
        thumbnail="dGVzdA==",
        coordinates=[126.978, 37.566],
    )
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
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    result = await compose_description(request, cache)

    assert result.description == "설명"
    assert len(result.warnings) == 0
    # captured_at=None이 describer에 전달됨
    call_args = mock_desc.describe_image.call_args
    assert call_args[0][2] is None  # captured_at


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_without_bbox(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """bbox 없이 요청해도 정상 동작하는지 검증."""
    request = DescribeRequest(
        thumbnail="dGVzdA==",
        coordinates=[126.978, 37.566],
        captured_at="2025-06-15T00:00:00Z",
    )
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
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    result = await compose_description(request, cache)

    assert result.description == "설명"
    assert len(result.warnings) == 0
    call_args = mock_desc.describe_image.call_args
    assert call_args[0][6] is None  # bbox


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_polar_coordinates(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """극지방 좌표(남극)로 요청이 정상 처리되는지 검증."""
    request = DescribeRequest(
        thumbnail="dGVzdA==",
        coordinates=[0.0, -89.99],
        captured_at="2025-01-01T00:00:00Z",
    )
    mock_geo.geocode = AsyncMock(
        return_value=Location(
            country="Antarctica", country_code="aq", region="Antarctica",
            place_name="South Pole", lat=-89.99, lon=0.0,
        )
    )
    mock_lc.get_land_cover = AsyncMock(
        return_value=LandCover(classes=[], summary="빙하")
    )
    mock_desc.describe_image = AsyncMock(return_value="극지 설명")
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    result = await compose_description(request, cache)

    assert result.description == "극지 설명"
    assert result.location.country == "Antarctica"
    assert len(result.warnings) == 0


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_dateline_coordinates(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """날짜변경선 근처 좌표로 요청이 정상 처리되는지 검증."""
    request = DescribeRequest(
        thumbnail="dGVzdA==",
        coordinates=[179.99, 0.0],
        captured_at="2025-01-01T00:00:00Z",
    )
    mock_geo.geocode = AsyncMock(
        return_value=Location(
            country="Fiji", country_code="fj", region="Pacific",
            place_name="Date Line", lat=0.0, lon=179.99,
        )
    )
    mock_lc.get_land_cover = AsyncMock(
        return_value=LandCover(classes=[], summary="해양")
    )
    mock_desc.describe_image = AsyncMock(return_value="태평양 설명")
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    result = await compose_description(request, cache)

    assert result.description == "태평양 설명"
    assert len(result.warnings) == 0


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_describer_fail_context_ok(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """Phase 2에서 describer만 실패해도 context는 정상 반환되는지 검증."""
    mock_geo.geocode = AsyncMock(
        return_value=Location(
            country="대한민국", country_code="kr", region="서울",
            city="중구", place_name="서울특별시", lat=37.566, lon=126.978,
        )
    )
    mock_lc.get_land_cover = AsyncMock(
        return_value=LandCover(classes=[], summary="정보 없음")
    )
    mock_desc.describe_image = AsyncMock(side_effect=Exception("Gemini API error"))
    mock_ctx.research_context = AsyncMock(
        return_value=Context(
            events=[
                Event(
                    title="뉴스", date="2025-06",
                    source_url="https://example.com", relevance="high",
                )
            ],
            summary="뉴스 요약",
        )
    )

    result = await compose_description(_make_request(), cache)

    assert result.description is None
    assert result.context is not None
    assert result.context.summary == "뉴스 요약"
    assert len(result.warnings) == 1
    assert result.warnings[0].module == "describer"


@patch("app.services.composer.context")
@patch("app.services.composer.describer")
@patch("app.services.composer.landcover")
@patch("app.services.composer.geocoder")
async def test_compose_timing_logs_emitted(mock_geo, mock_lc, mock_desc, mock_ctx, cache):
    """Phase 타이밍 로그(phase1_complete, phase2_complete, compose_complete)가 출력되는지 검증."""
    mock_geo.geocode = AsyncMock(
        return_value=Location(
            country="대한민국", country_code="kr", region="서울",
            city="중구", place_name="서울특별시", lat=37.566, lon=126.978,
        )
    )
    mock_lc.get_land_cover = AsyncMock(return_value=LandCover(classes=[], summary="정보 없음"))
    mock_desc.describe_image = AsyncMock(return_value="설명")
    mock_ctx.research_context = AsyncMock(return_value=Context(events=[], summary="없음"))

    with structlog.testing.capture_logs() as logs:
        await compose_description(_make_request(), cache)

    event_names = [log["event"] for log in logs]
    assert "phase1_complete" in event_names
    assert "phase2_complete" in event_names
    assert "compose_complete" in event_names

    compose_log = next(entry for entry in logs if entry["event"] == "compose_complete")
    assert "total_duration_ms" in compose_log
    assert isinstance(compose_log["total_duration_ms"], int)
    assert compose_log["total_duration_ms"] >= 0
    assert compose_log["warning_count"] == 0
