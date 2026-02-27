from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.schemas import (
    Context,
    DescribeRequest,
    DescribeResponse,
    LandCover,
    Location,
)
from app.config import settings
from app.db import supabase as db
from app.services.composer import compose_description
from app.utils.errors import DescriptorError

router = APIRouter()
api_key_header = APIKeyHeader(name="X-API-Key")
limiter = Limiter(key_func=get_remote_address)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if api_key != settings.api_key:
        raise DescriptorError(
            status_code=401,
            code="INVALID_API_KEY",
            message="Invalid API key",
        )
    return api_key


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.post("/describe", response_model=DescribeResponse)
@limiter.limit("10/minute")
async def describe(
    body: DescribeRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    lon, lat = body.coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise DescriptorError(
            status_code=400,
            code="INVALID_COORDINATES",
            message="Invalid coordinates range",
            details={"lon": lon, "lat": lat},
        )

    if not body.thumbnail.startswith("http") and len(body.thumbnail) > 5 * 1024 * 1024:
        raise DescriptorError(
            status_code=422,
            code="THUMBNAIL_TOO_LARGE",
            message="Thumbnail too large (max 5MB)",
            details={"size": len(body.thumbnail), "max": 5 * 1024 * 1024},
        )

    cache = request.app.state.cache
    result = await compose_description(body, cache)

    # Save to Supabase if cog_image_id provided
    if body.cog_image_id and result.description:
        await db.save_description(
            cog_image_id=body.cog_image_id,
            coordinates=body.coordinates,
            captured_at=body.captured_at,
            location=result.location.model_dump() if result.location else None,
            land_cover=result.land_cover.model_dump() if result.land_cover else None,
            description=result.description,
            context=result.context.model_dump() if result.context else None,
        )

    return result


@router.post("/geocode", response_model=Location)
@limiter.limit("10/minute")
async def geocode_endpoint(
    body: DescribeRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    from app.modules.geocoder import geocode

    lon, lat = body.coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise DescriptorError(
            status_code=400,
            code="INVALID_COORDINATES",
            message="Invalid coordinates range",
        )
    cache = request.app.state.cache
    return await geocode(lon, lat, cache)


@router.post("/landcover", response_model=LandCover)
@limiter.limit("10/minute")
async def landcover_endpoint(
    body: DescribeRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    from app.modules.landcover import get_land_cover

    lon, lat = body.coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise DescriptorError(
            status_code=400,
            code="INVALID_COORDINATES",
            message="Invalid coordinates range",
        )
    cache = request.app.state.cache
    return await get_land_cover(lon, lat, cache)


@router.post("/context", response_model=Context)
@limiter.limit("10/minute")
async def context_endpoint(
    body: DescribeRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    from app.modules.context import research_context

    lon, lat = body.coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise DescriptorError(
            status_code=400,
            code="INVALID_COORDINATES",
            message="Invalid coordinates range",
        )
    cache = request.app.state.cache
    place_name = f"{lat}, {lon}"
    return await research_context(place_name, body.captured_at, cache)


@router.get("/descriptions/{cog_image_id}")
async def get_description(cog_image_id: str):
    result = await db.get_description(cog_image_id)
    if result is None:
        raise DescriptorError(
            status_code=404,
            code="NOT_FOUND",
            message=f"Description not found for cog_image_id: {cog_image_id}",
        )
    return result
