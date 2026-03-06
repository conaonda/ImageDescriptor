import asyncio
import hashlib
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter

from app.api.schemas import (
    BatchDescribeItem,
    BatchDescribeRequest,
    BatchDescribeResponse,
    BatchItemResult,
    CacheStatsResponse,
    CircuitBreakerResponse,
    Context,
    DescribeRequest,
    DescribeResponse,
    DescriptionListResponse,
    ErrorResponse,  # kept for backward compat
    HealthResponse,
    LandCover,
    Location,
    Warning,
)
from app.auth import authenticate
from app.utils.errors import ProblemDetail
from app.config import settings
from app.db import supabase as db
from app.services.composer import compose_description, get_breaker_statuses
from app.utils.errors import DescriptorError
from app.utils.rate_limit import get_real_ip
from app.utils.timeout import apply_timeout

logger = structlog.get_logger()

router = APIRouter()
limiter = Limiter(key_func=get_real_ip)


async def _describe_and_save(item: DescribeRequest, cache) -> DescribeResponse:
    result = await compose_description(item, cache)
    if item.cog_image_id and result.description:
        saved = await db.save_description(
            cog_image_id=item.cog_image_id,
            coordinates=item.coordinates,
            captured_at=item.captured_at,
            location=result.location.model_dump() if result.location else None,
            land_cover=result.land_cover.model_dump() if result.land_cover else None,
            description=result.description,
            context=result.context.model_dump() if result.context else None,
        )
        result.saved = saved
        if not saved:
            result.warnings.append(
                Warning(module="supabase", error="Failed to save description to database")
            )
    return result


@router.get(
    "/cache/stats",
    response_model=CacheStatsResponse,
    tags=["system"],
    summary="캐시 통계 조회",
    description="SQLite 캐시의 히트/미스 통계 및 항목 수를 반환합니다.",
)
async def cache_stats(request: Request):
    cache = request.app.state.cache
    return await cache.stats()


@router.get(
    "/circuits",
    response_model=CircuitBreakerResponse,
    tags=["system"],
    summary="Circuit breaker 상태 조회",
    description="각 외부 서비스의 circuit breaker 상태"
    "(open/closed, 실패 횟수, cooldown 잔여 시간)를 반환합니다.",
)
async def circuit_breaker_status():
    return CircuitBreakerResponse(breakers=get_breaker_statuses())


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="헬스체크",
    description="서비스 상태와 버전 정보, 의존성 상태를 반환합니다.",
    responses={
        503: {
            "model": HealthResponse,
            "description": "서비스 비정상 (unhealthy 또는 shutting_down)",
        },
    },
)
async def health(request: Request):
    try:
        ver = version("cognito-descriptor")
    except PackageNotFoundError:
        ver = "unknown"

    cache = request.app.state.cache
    cache_ok = await cache.ping()
    supabase_ok = await db.ping()

    checks = {
        "supabase": "ok" if supabase_ok else "fail",
        "cache": "ok" if cache_ok else "fail",
    }

    all_fail = not supabase_ok and not cache_ok
    any_fail = not supabase_ok or not cache_ok

    if all_fail:
        status = "unhealthy"
    elif any_fail:
        status = "degraded"
    else:
        status = "ok"

    from app.main import is_shutting_down

    if is_shutting_down():
        status = "shutting_down"

    body = {"status": status, "version": ver, "checks": checks}
    status_code = 503 if all_fail or is_shutting_down() else 200
    return JSONResponse(content=body, status_code=status_code)


def _generate_etag(body_bytes: bytes) -> str:
    return f'"{hashlib.md5(body_bytes).hexdigest()}"'  # noqa: S324


@router.post(
    "/describe",
    response_model=DescribeResponse,
    tags=["analysis"],
    summary="위성영상 통합 분석",
    description=(
        "썸네일과 좌표를 입력받아 역지오코딩, 토지피복 분류, "
        "Gemini AI 영상 설명, 맥락 정보를 통합 생성합니다."
    ),
    responses={
        304: {"description": "캐시 유효 (Not Modified)"},
        422: {
            "model": ProblemDetail,
            "description": "유효하지 않은 요청 (좌표 범위 초과, 썸네일 과대 등)",
        },
        429: {"description": "요청 횟수 초과 (Rate Limit Exceeded)"},
    },
)
@limiter.limit(lambda: settings.rate_limit)
async def describe(
    body: DescribeRequest,
    request: Request,
    _auth: dict = Depends(authenticate),
    if_none_match: str | None = Header(None),
):
    cache = request.app.state.cache
    result = await apply_timeout(_describe_and_save(body, cache), request)

    body_bytes = result.model_dump_json().encode()
    etag = _generate_etag(body_bytes)

    if if_none_match and if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})

    cache_control = "private, max-age=3600" if result.cached else "no-cache"
    return JSONResponse(
        content=result.model_dump(mode="json"),
        headers={"ETag": etag, "Cache-Control": cache_control},
    )


@router.post(
    "/describe/batch",
    response_model=BatchDescribeResponse,
    tags=["analysis"],
    summary="위성영상 배치 분석",
    description=(
        "최대 10건의 분석 요청을 병렬 처리합니다. 개별 실패 시 해당 항목만 에러를 반환합니다."
    ),
    responses={
        422: {"model": ProblemDetail, "description": "유효하지 않은 요청"},
        429: {"description": "요청 횟수 초과"},
    },
)
@limiter.limit(lambda: settings.rate_limit)
async def describe_batch(
    body: BatchDescribeRequest,
    request: Request,
    _auth: dict = Depends(authenticate),
):
    cache = request.app.state.cache

    async def _process_one(index: int, raw_item: BatchDescribeItem) -> BatchItemResult:
        try:
            item = DescribeRequest.model_validate(raw_item.model_dump())
            result = await _describe_and_save(item, cache)
            return BatchItemResult(index=index, result=result)
        except Exception as e:
            return BatchItemResult(index=index, error=str(e))

    semaphore = asyncio.Semaphore(settings.batch_concurrency)

    async def _limited(index: int, item: BatchDescribeItem) -> BatchItemResult:
        async with semaphore:
            return await _process_one(index, item)

    results = await asyncio.gather(*[_limited(i, item) for i, item in enumerate(body.items)])
    succeeded = sum(1 for r in results if r.result is not None)
    logger.info(
        "batch_complete",
        total=len(body.items),
        succeeded=succeeded,
        failed=len(body.items) - succeeded,
    )
    return BatchDescribeResponse(
        results=list(results),
        total=len(body.items),
        succeeded=succeeded,
        failed=len(body.items) - succeeded,
    )


@router.post(
    "/geocode",
    response_model=Location,
    tags=["data"],
    summary="역지오코딩",
    description="좌표를 입력받아 Nominatim 기반 역지오코딩 결과를 반환합니다.",
    responses={
        429: {"description": "요청 횟수 초과"},
    },
)
@limiter.limit(lambda: settings.rate_limit)
async def geocode_endpoint(
    body: DescribeRequest,
    request: Request,
    _auth: dict = Depends(authenticate),
):
    from app.modules.geocoder import geocode

    lon, lat = body.coordinates
    cache = request.app.state.cache
    return await geocode(lon, lat, cache)


@router.post(
    "/landcover",
    response_model=LandCover,
    tags=["data"],
    summary="토지피복 분류",
    description="좌표를 입력받아 Overpass API 기반 토지피복 분류 결과를 반환합니다.",
    responses={
        429: {"description": "요청 횟수 초과"},
    },
)
@limiter.limit(lambda: settings.rate_limit)
async def landcover_endpoint(
    body: DescribeRequest,
    request: Request,
    _auth: dict = Depends(authenticate),
):
    from app.modules.landcover import get_land_cover

    lon, lat = body.coordinates
    cache = request.app.state.cache
    return await get_land_cover(lon, lat, cache)


@router.post(
    "/context",
    response_model=Context,
    tags=["data"],
    summary="맥락 정보 조회",
    description="좌표와 촬영일자를 기반으로 DuckDuckGo API에서 관련 맥락 정보를 검색합니다.",
    responses={
        429: {"description": "요청 횟수 초과"},
    },
)
@limiter.limit(lambda: settings.rate_limit)
async def context_endpoint(
    body: DescribeRequest,
    request: Request,
    _auth: dict = Depends(authenticate),
):
    from app.modules.context import research_context

    lon, lat = body.coordinates
    cache = request.app.state.cache
    place_name = f"{lat}, {lon}"
    return await research_context(place_name, body.captured_at, cache)


@router.get(
    "/descriptions",
    response_model=DescriptionListResponse,
    tags=["analysis"],
    summary="설명 이력 목록 조회",
    description="저장된 설명 목록을 페이지네이션으로 조회합니다.",
    responses={
        429: {"description": "요청 횟수 초과"},
    },
)
@limiter.limit("30/minute")
async def list_descriptions(
    request: Request,
    offset: int = Query(default=0, ge=0, description="시작 위치"),
    limit: int = Query(default=20, ge=1, le=100, description="페이지 크기"),
    created_after: datetime | None = Query(
        default=None,
        description="이 시각 이후 항목만 조회 (ISO 8601)",
    ),
    created_before: datetime | None = Query(
        default=None,
        description="이 시각 이전 항목만 조회 (ISO 8601)",
    ),
    _auth: dict = Depends(authenticate),
):
    result = await db.list_descriptions(
        offset=offset,
        limit=limit,
        created_after=created_after.isoformat() if created_after else None,
        created_before=created_before.isoformat() if created_before else None,
    )
    return DescriptionListResponse(
        items=result["items"],
        total=result["total"],
        offset=offset,
        limit=limit,
    )


@router.get(
    "/descriptions/{cog_image_id}",
    tags=["analysis"],
    summary="저장된 설명 조회",
    description="cog_image_id로 Supabase에 저장된 분석 결과를 조회합니다.",
    responses={
        404: {"model": ProblemDetail, "description": "해당 ID의 설명을 찾을 수 없음"},
        429: {"description": "요청 횟수 초과"},
    },
)
@limiter.limit("30/minute")
async def get_description(
    cog_image_id: str,
    request: Request,
    _auth: dict = Depends(authenticate),
):
    result = await db.get_description(cog_image_id)
    if result is None:
        logger.info("description_not_found", cog_image_id=cog_image_id)
        raise DescriptorError(
            status_code=404,
            code="NOT_FOUND",
            message=f"Description not found for cog_image_id: {cog_image_id}",
        )
    return result


@router.delete(
    "/descriptions/{cog_image_id}",
    status_code=204,
    tags=["analysis"],
    summary="설명 삭제",
    description="cog_image_id로 저장된 분석 결과를 삭제합니다.",
    responses={
        404: {"model": ProblemDetail, "description": "해당 ID의 설명을 찾을 수 없음"},
        429: {"description": "요청 횟수 초과"},
    },
)
@limiter.limit("30/minute")
async def delete_description(
    cog_image_id: str,
    request: Request,
    _auth: dict = Depends(authenticate),
):
    try:
        deleted = await db.delete_description(cog_image_id)
    except Exception as e:
        logger.error("delete_description_error", cog_image_id=cog_image_id, error=str(e))
        raise DescriptorError(
            status_code=500,
            code="INTERNAL_ERROR",
            message="Failed to delete description due to a database error",
        )
    if not deleted:
        logger.info("description_not_found", cog_image_id=cog_image_id)
        raise DescriptorError(
            status_code=404,
            code="NOT_FOUND",
            message=f"Description not found for cog_image_id: {cog_image_id}",
        )
    return Response(status_code=204)
