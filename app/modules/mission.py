import httpx
import structlog

from app.api.schemas import Mission
from app.cache.store import CacheStore
from app.utils.retry import retry_http

logger = structlog.get_logger()

STAC_BASE_URL = "https://earth-search.aws.element84.com/v1"

_COLLECTION_PROCESSING_LEVEL = {
    "sentinel-2-l1c": "L1C",
    "sentinel-2-l2a": "L2A",
    "sentinel-2-c1-l2a": "L2A",
}


@retry_http
async def _fetch_stac_item(stac_id: str) -> httpx.Response:
    collection = _guess_collection(stac_id)
    url = f"{STAC_BASE_URL}/collections/{collection}/items/{stac_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp


def _guess_collection(stac_id: str) -> str:
    stac_id_upper = stac_id.upper()
    if "_L2A" in stac_id_upper:
        return "sentinel-2-c1-l2a"
    if "_L1C" in stac_id_upper:
        return "sentinel-2-l1c"
    return "sentinel-2-c1-l2a"


def _parse_mission(data: dict) -> dict:
    props = data.get("properties", {})

    instruments = props.get("instruments") or ["unknown"]
    instrument = ", ".join(instruments)

    collection_id = data.get("collection", "")
    default_level = props.get("s2:processing_level")
    processing_level = _COLLECTION_PROCESSING_LEVEL.get(collection_id, default_level)

    eo_bands = props.get("eo:bands")
    spectral_bands = len(eo_bands) if eo_bands else None

    return {
        "platform": props.get("platform", "unknown"),
        "instrument": instrument,
        "constellation": props.get("constellation"),
        "processing_level": processing_level,
        "cloud_cover": props.get("eo:cloud_cover"),
        "gsd": props.get("gsd"),
        "spectral_bands": spectral_bands,
    }


async def get_mission_metadata(stac_id: str | None, cache: CacheStore) -> Mission | None:
    if not stac_id:
        return None

    cache_key = f"mission:{stac_id}"
    cached = await cache.get(cache_key)
    if cached:
        logger.debug("mission cache hit", stac_id=stac_id)
        return Mission(**cached)

    resp = await _fetch_stac_item(stac_id)
    data = resp.json()
    mission_dict = _parse_mission(data)

    await cache.set(cache_key, mission_dict, ttl_days=365)
    logger.info("mission metadata fetched", stac_id=stac_id, platform=mission_dict["platform"])
    return Mission(**mission_dict)
