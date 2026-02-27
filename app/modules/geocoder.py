import asyncio

import httpx
import structlog

from app.api.schemas import Location
from app.cache.store import CacheStore
from app.config import settings

logger = structlog.get_logger()

# Nominatim 사용 정책: 1 req/sec
_semaphore = asyncio.Semaphore(1)
_last_request_time = 0.0


def _round_coords(lon: float, lat: float, decimals: int = 3) -> tuple[float, float]:
    """좌표를 반올림하여 캐시 키 생성 (~111m 정밀도)."""
    return round(lon, decimals), round(lat, decimals)


async def geocode(lon: float, lat: float, cache: CacheStore) -> Location:
    rlon, rlat = _round_coords(lon, lat)
    cache_key = f"geocode:{rlon}:{rlat}"

    cached = await cache.get(cache_key)
    if cached:
        logger.debug("geocoder cache hit", lon=rlon, lat=rlat)
        return Location(**cached)

    global _last_request_time
    async with _semaphore:
        # 1 req/sec 속도 제한
        now = asyncio.get_event_loop().time()
        wait = max(0, 1.0 - (now - _last_request_time))
        if wait > 0:
            await asyncio.sleep(wait)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.nominatim_url}/reverse",
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "jsonv2",
                    "accept-language": "ko",
                    "zoom": 14,
                },
                headers={"User-Agent": "COGnito/1.2 (image-descriptor)"},
                timeout=10.0,
            )
            resp.raise_for_status()
            _last_request_time = asyncio.get_event_loop().time()

    data = resp.json()
    address = data.get("address", {})

    location = Location(
        country=address.get("country", data.get("display_name", "Unknown")),
        country_code=address.get("country_code", ""),
        region=address.get("state", address.get("province", "")),
        city=address.get("city", address.get("town", address.get("village"))),
        place_name=data.get("display_name", ""),
        lat=lat,
        lon=lon,
    )

    await cache.set(cache_key, location.model_dump(), ttl_days=30)
    logger.info("geocoder result", country=location.country, region=location.region)
    return location
