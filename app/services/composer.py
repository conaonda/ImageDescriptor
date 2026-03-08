import asyncio
import time
from collections.abc import Awaitable

import structlog

from app.api.schemas import DescribeRequest, DescribeResponse, Warning
from app.cache.store import CacheStore
from app.modules import context, describer, geocoder, landcover, mission
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.metrics import (
    description_requests_total,
    external_api_duration,
    external_api_requests,
)

logger = structlog.get_logger()

# Circuit breakers per external service (5 failures → 30s cooldown)
_breakers = {
    "geocoder": CircuitBreaker("geocoder"),
    "landcover": CircuitBreaker("landcover"),
    "describer": CircuitBreaker("describer"),
    "context": CircuitBreaker("context"),
    "mission": CircuitBreaker("mission"),
}


def get_breaker_statuses() -> list[dict]:
    return [cb.get_status() for cb in _breakers.values()]


async def _safe_call(name: str, coro: Awaitable, warnings: list[Warning]):
    cb = _breakers[name]
    if cb.is_open:
        warnings.append(Warning(module=name, error="Circuit breaker open"))
        return None
    t0 = time.monotonic()
    try:
        result = await coro
        cb.record_success()
        external_api_requests.labels(service=name, status="success").inc()
        external_api_duration.labels(service=name).observe(time.monotonic() - t0)
        return result
    except Exception as e:
        cb.record_failure()
        external_api_requests.labels(service=name, status="error").inc()
        external_api_duration.labels(service=name).observe(time.monotonic() - t0)
        logger.error("external_call_failed", service=name, error=str(e))
        warnings.append(Warning(module=name, error=str(e)))
        return None


async def compose_description(request: DescribeRequest, cache: CacheStore) -> DescribeResponse:
    warnings: list[Warning] = []
    lon, lat = request.coordinates
    t_start = time.monotonic()
    status = "error"
    try:
        # Phase 1: Geocoder + LandCover 병렬 실행 (Describer의 입력이 됨)
        t_phase1 = time.monotonic()
        geo_task = asyncio.create_task(
            _safe_call("geocoder", geocoder.geocode(lon, lat, cache), warnings)
        )
        lc_task = asyncio.create_task(
            _safe_call("landcover", landcover.get_land_cover(lon, lat, cache), warnings)
        )
        mission_task = asyncio.create_task(
            _safe_call(
                "mission", mission.get_mission_metadata(request.stac_id, cache), warnings
            )
        )
        location, land_cover_result, mission_result = await asyncio.gather(
            geo_task,
            lc_task,
            mission_task,
        )
        logger.info(
            "phase1_complete", duration_ms=round((time.monotonic() - t_phase1) * 1000)
        )

        # Phase 2: Describer + Context 병렬 실행 (Phase 1 결과 활용)
        place_name = location.place_name if location else f"{lat}, {lon}"
        lc_summary = land_cover_result.summary if land_cover_result else "정보 없음"

        t_phase2 = time.monotonic()
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
        desc_result, context_result = await asyncio.gather(desc_task, ctx_task)
        logger.info(
            "phase2_complete", duration_ms=round((time.monotonic() - t_phase2) * 1000)
        )

        if desc_result is not None:
            description, cached = desc_result
        else:
            description, cached = None, False

        total_ms = round((time.monotonic() - t_start) * 1000)
        status = "success" if description else "error"
        logger.info("compose_complete", total_duration_ms=total_ms, warning_count=len(warnings))

        return DescribeResponse(
            description=description,
            location=location,
            land_cover=land_cover_result,
            context=context_result,
            mission=mission_result,
            warnings=warnings,
            cached=cached,
        )
    finally:
        description_requests_total.labels(status=status).inc()
