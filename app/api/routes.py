import asyncio
from importlib.metadata import PackageNotFoundError, version

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter

from app.api.schemas import (
    BatchDescribeItem,
    BatchDescribeRequest,
    BatchDescribeResponse,
    BatchItemResult,
    Context,
    DescribeRequest,
    DescribeResponse,
    ErrorResponse,
    LandCover,
    Location,
    Warning,
)
from app.auth import authenticate
from app.config import settings
from app.db import supabase as db
from app.services.composer import compose_description
from app.utils.errors import DescriptorError
from app.utils.rate_limit import get_real_ip

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
    tags=["system"],
    summary="캐시 통계 조회",
    description="SQLite 캐시의 히트/미스 통계 및 항목 수를 반환합니다.",
)
async def cache_stats(request: Request):
    cache = request.app.state.cache
    return await cache.stats()


@router.get(
    "/health",
    tags=["system"],
    summary="헬스체크",
    description="서비스 상태와 버전 정보, 의존성 상태를 반환합니다.",
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

    body = {"status": status, "version": ver, "checks": checks}
    status_code = 503 if all_fail else 200
    return JSONResponse(content=body, status_code=status_code)


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
        422: {
            "model": ErrorResponse,
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
):
    cache = request.app.state.cache
    return await _describe_and_save(body, cache)


@router.post(
    "/describe/batch",
    response_model=BatchDescribeResponse,
    tags=["analysis"],
    summary="위성영상 배치 분석",
    description=(
        "최대 10건의 분석 요청을 병렬 처리합니다. 개별 실패 시 해당 항목만 에러를 반환합니다."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "유효하지 않은 요청"},
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

    results = await asyncio.gather(*[_process_one(i, item) for i, item in enumerate(body.items)])
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
    "/descriptions/{cog_image_id}",
    tags=["analysis"],
    summary="저장된 설명 조회",
    description="cog_image_id로 Supabase에 저장된 분석 결과를 조회합니다.",
    responses={
        404: {"model": ErrorResponse, "description": "해당 ID의 설명을 찾을 수 없음"},
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
