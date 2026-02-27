import asyncio

import structlog

from app.api.schemas import DescribeRequest, DescribeResponse, Warning
from app.cache.store import CacheStore
from app.modules import context, describer, geocoder, landcover
from app.utils.circuit_breaker import CircuitBreaker

logger = structlog.get_logger()

# Circuit breakers per external service (5 failures → 30s cooldown)
_breakers = {
    "geocoder": CircuitBreaker("geocoder"),
    "landcover": CircuitBreaker("landcover"),
    "describer": CircuitBreaker("describer"),
    "context": CircuitBreaker("context"),
}


async def compose_description(
    request: DescribeRequest, cache: CacheStore
) -> DescribeResponse:
    warnings: list[Warning] = []
    lon, lat = request.coordinates

    # Phase 1: Geocoder + LandCover 병렬 실행 (Describer의 입력이 됨)
    geo_task = asyncio.create_task(_safe_geocode(lon, lat, cache, warnings))
    lc_task = asyncio.create_task(_safe_landcover(lon, lat, cache, warnings))
    location, land_cover_result = await asyncio.gather(geo_task, lc_task)

    # Phase 2: Describer + Context 병렬 실행 (Phase 1 결과 활용)
    place_name = location.place_name if location else f"{lat}, {lon}"
    lc_summary = land_cover_result.summary if land_cover_result else "정보 없음"

    desc_task = asyncio.create_task(
        _safe_describe(
            request.thumbnail, place_name, request.captured_at, lc_summary,
            cache, request.cog_image_id, warnings,
        )
    )
    ctx_task = asyncio.create_task(
        _safe_context(place_name, request.captured_at, cache, warnings)
    )
    description, context_result = await asyncio.gather(desc_task, ctx_task)

    return DescribeResponse(
        description=description,
        location=location,
        land_cover=land_cover_result,
        context=context_result,
        warnings=warnings,
        cached=False,
    )


async def _safe_geocode(lon, lat, cache, warnings):
    cb = _breakers["geocoder"]
    if cb.is_open:
        warnings.append(Warning(module="geocoder", error="Circuit breaker open"))
        return None
    try:
        result = await geocoder.geocode(lon, lat, cache)
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        logger.error("geocoder failed", error=str(e))
        warnings.append(Warning(module="geocoder", error=str(e)))
        return None


async def _safe_landcover(lon, lat, cache, warnings):
    cb = _breakers["landcover"]
    if cb.is_open:
        warnings.append(Warning(module="landcover", error="Circuit breaker open"))
        return None
    try:
        result = await landcover.get_land_cover(lon, lat, cache)
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        logger.error("landcover failed", error=str(e))
        warnings.append(Warning(module="landcover", error=str(e)))
        return None


async def _safe_describe(
    thumbnail, place_name, captured_at, lc_summary, cache, cog_image_id, warnings
):
    cb = _breakers["describer"]
    if cb.is_open:
        warnings.append(Warning(module="describer", error="Circuit breaker open"))
        return None
    try:
        result = await describer.describe_image(
            thumbnail, place_name, captured_at, lc_summary, cache, cog_image_id
        )
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        logger.error("describer failed", error=str(e))
        warnings.append(Warning(module="describer", error=str(e)))
        return None


async def _safe_context(place_name, captured_at, cache, warnings):
    cb = _breakers["context"]
    if cb.is_open:
        warnings.append(Warning(module="context", error="Circuit breaker open"))
        return None
    try:
        result = await context.research_context(place_name, captured_at, cache)
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        logger.error("context failed", error=str(e))
        warnings.append(Warning(module="context", error=str(e)))
        return None
