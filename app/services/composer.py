import asyncio
from collections.abc import Awaitable

import structlog

from app.api.schemas import DescribeRequest, DescribeResponse, Warning
from app.cache.store import CacheStore
from app.modules import context, describer, geocoder, landcover, mission
from app.utils.circuit_breaker import CircuitBreaker

logger = structlog.get_logger()

# Circuit breakers per external service (5 failures → 30s cooldown)
_breakers = {
    "geocoder": CircuitBreaker("geocoder"),
    "landcover": CircuitBreaker("landcover"),
    "describer": CircuitBreaker("describer"),
    "context": CircuitBreaker("context"),
    "mission": CircuitBreaker("mission"),
}


async def _safe_call(name: str, coro: Awaitable, warnings: list[Warning]):
    cb = _breakers[name]
    if cb.is_open:
        warnings.append(Warning(module=name, error="Circuit breaker open"))
        return None
    try:
        result = await coro
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        logger.error(f"{name} failed", error=str(e))
        warnings.append(Warning(module=name, error=str(e)))
        return None


async def compose_description(request: DescribeRequest, cache: CacheStore) -> DescribeResponse:
    warnings: list[Warning] = []
    lon, lat = request.coordinates

    # Phase 1: Geocoder + LandCover + Mission 병렬 실행
    geo_task = asyncio.create_task(
        _safe_call("geocoder", geocoder.geocode(lon, lat, cache), warnings)
    )
    lc_task = asyncio.create_task(
        _safe_call("landcover", landcover.get_land_cover(lon, lat, cache), warnings)
    )
    mission_task = asyncio.create_task(
        _safe_call("mission", mission.get_mission_metadata(request.stac_id, cache), warnings)
    ) if request.stac_id else None
    phase1_tasks = [geo_task, lc_task]
    if mission_task:
        phase1_tasks.append(mission_task)
    phase1_results = await asyncio.gather(*phase1_tasks)
    location, land_cover_result = phase1_results[0], phase1_results[1]
    mission_result = phase1_results[2] if mission_task else None

    # Phase 2: Describer + Context 병렬 실행 (Phase 1 결과 활용)
    place_name = location.place_name if location else f"{lat}, {lon}"
    lc_summary = land_cover_result.summary if land_cover_result else "정보 없음"

    desc_task = asyncio.create_task(
        _safe_call(
            "describer",
            describer.describe_image(
                request.thumbnail,
                place_name,
                request.captured_at,
                lc_summary,
                cache,
                request.cog_image_id,
                request.bbox,
            ),
            warnings,
        )
    )
    region = location.region if location else ""
    city = location.city if location else None
    ctx_task = asyncio.create_task(
        _safe_call(
            "context",
            context.research_context(
                place_name, request.captured_at, cache, region=region, city=city
            ),
            warnings,
        )
    )
    description, context_result = await asyncio.gather(desc_task, ctx_task)

    return DescribeResponse(
        description=description,
        location=location,
        land_cover=land_cover_result,
        context=context_result,
        mission=mission_result,
        warnings=warnings,
        cached=False,
    )
