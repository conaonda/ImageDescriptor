import httpx
import structlog

from app.api.schemas import LandCover, LandCoverClass
from app.cache.store import CacheStore
from app.config import settings

logger = structlog.get_logger()

# OSM landuse/natural/leisure 태그 → 한국어 매핑
TAG_LABELS: dict[str, str] = {
    "residential": "주거지역",
    "commercial": "상업지역",
    "industrial": "산업지역",
    "retail": "상업지역",
    "farmland": "농경지",
    "farm": "농경지",
    "orchard": "과수원",
    "vineyard": "포도밭",
    "forest": "산림",
    "wood": "산림",
    "grass": "초지",
    "meadow": "초지",
    "scrub": "관목지",
    "heath": "황무지",
    "water": "수역",
    "wetland": "습지",
    "bare_rock": "나지",
    "sand": "모래",
    "beach": "해변",
    "quarry": "채석장",
    "landfill": "매립지",
    "cemetery": "묘지",
    "park": "공원",
    "recreation_ground": "운동장",
    "garden": "정원",
    "military": "군사지역",
    "construction": "건설현장",
    "railway": "철도",
    "allotments": "텃밭",
}


def _round_coords(lon: float, lat: float) -> tuple[float, float]:
    """소수점 2자리 (~1.1km 정밀도)."""
    return round(lon, 2), round(lat, 2)


async def get_land_cover(
    lon: float, lat: float, cache: CacheStore
) -> LandCover:
    rlon, rlat = _round_coords(lon, lat)
    cache_key = f"landcover:{rlon}:{rlat}"

    cached = await cache.get(cache_key)
    if cached:
        logger.debug("landcover cache hit", lon=rlon, lat=rlat)
        return LandCover(**cached)

    query = f"""
[out:json][timeout:10];
(
  way["landuse"](around:500,{lat},{lon});
  way["natural"](around:500,{lat},{lon});
  way["leisure"](around:500,{lat},{lon});
  relation["landuse"](around:500,{lat},{lon});
);
out tags;
"""

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            settings.overpass_url,
            data={"data": query},
            timeout=15.0,
        )
        resp.raise_for_status()

    elements = resp.json().get("elements", [])

    # 태그 카운트 집계
    tag_counts: dict[str, int] = {}
    for el in elements:
        tags = el.get("tags", {})
        for key in ("landuse", "natural", "leisure"):
            val = tags.get(key)
            if val:
                tag_counts[val] = tag_counts.get(val, 0) + 1

    total = sum(tag_counts.values()) or 1
    classes = []
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        pct = round(count / total * 100)
        classes.append(LandCoverClass(
            type=tag,
            label=TAG_LABELS.get(tag, tag),
            percentage=pct,
        ))

    summary_parts = [f"{c.label} {c.percentage}%" for c in classes[:5]]
    summary = ", ".join(summary_parts) if summary_parts else "정보 없음"

    result = LandCover(classes=classes, summary=summary)
    await cache.set(cache_key, result.model_dump(), ttl_days=90)
    logger.info("landcover result", classes_count=len(classes), summary=summary)
    return result
