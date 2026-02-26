from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.api.schemas import DescribeRequest, DescribeResponse
from app.config import settings
from app.services.composer import compose_description

router = APIRouter()
api_key_header = APIKeyHeader(name="X-API-Key")


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.post("/describe", response_model=DescribeResponse)
async def describe(
    body: DescribeRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    # 입력 검증
    lon, lat = body.coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise HTTPException(status_code=400, detail="Invalid coordinates range")

    # 썸네일 크기 제한 (5MB)
    if len(body.thumbnail) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Thumbnail too large (max 5MB)")

    cache = request.app.state.cache
    return await compose_description(body, cache)
