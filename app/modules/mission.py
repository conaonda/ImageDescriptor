import httpx
import structlog

from app.api.schemas import Mission
from app.cache.store import CacheStore
from app.utils.retry import retry_http

logger = structlog.get_logger()

STAC_BASE_URL = "https://earth-search.aws.element84.com/v1"
STAC_COLLECTION = "sentinel-2-c1-l2a"

# Sentinel-2 L2A has 13 spectral bands
_S2_SPECTRAL_BANDS = 13


@retry_http
async def _fetch_stac_item(stac_id: str) -> httpx.Response:
    url = f"{STAC_BASE_URL}/collections/{STAC_COLLECTION}/items/{stac_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp


def _parse_stac_item(data: dict) -> Mission:
    props = data.get("properties", {})
    return Mission(
        platform=props.get("platform", "unknown"),
        instrument=",".join(props.get("instruments", ["unknown"])),
        constellation=props.get("constellation"),
        processing_level=props.get("processing:level"),
        cloud_cover=props.get("eo:cloud_cover"),
        gsd=props.get("gsd", 10.0),
        spectral_bands=_S2_SPECTRAL_BANDS,
    )


async def get_mission_metadata(stac_id: str, cache: CacheStore) -> Mission | None:
    if not stac_id:
        return None

    cache_key = f"mission:{stac_id}"
    cached = await cache.get(cache_key)
    if cached:
        logger.debug("mission cache hit", stac_id=stac_id)
        return Mission(**cached)

    resp = await _fetch_stac_item(stac_id)
    result = _parse_stac_item(resp.json())
    await cache.set(cache_key, result.model_dump(), ttl_days=365)
    logger.info("mission metadata fetched", stac_id=stac_id, platform=result.platform)
    return result
