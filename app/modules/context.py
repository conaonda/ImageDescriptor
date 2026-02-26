import httpx
import structlog

from app.api.schemas import Context, Event
from app.cache.store import CacheStore

logger = structlog.get_logger()


async def research_context(
    place_name: str,
    captured_at: str,
    cache: CacheStore,
) -> Context:
    # 캐시 키: 지역명 + 월 단위
    month = captured_at[:7] if len(captured_at) >= 7 else captured_at
    cache_key = f"context:{place_name}:{month}"

    cached = await cache.get(cache_key)
    if cached:
        logger.debug("context cache hit", place=place_name, month=month)
        return Context(**cached)

    # DuckDuckGo Instant Answer API (MVP)
    query = f"{place_name} {month}"
    events: list[Event] = []

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

        # Instant Answer에서 관련 토픽 추출
        for topic in data.get("RelatedTopics", [])[:5]:
            text = topic.get("Text", "")
            url = topic.get("FirstURL", "")
            if text and url:
                events.append(Event(
                    title=text[:200],
                    date=month,
                    source_url=url,
                    relevance="low",
                ))
    except Exception as e:
        logger.warning("context research failed", error=str(e))

    summary = (
        f"{place_name} {month} 관련 정보 {len(events)}건 발견."
        if events
        else f"{place_name} {month}에 대한 관련 정보를 찾지 못했습니다."
    )

    result = Context(events=events, summary=summary)
    await cache.set(cache_key, result.model_dump(), ttl_days=7)
    logger.info("context result", events_count=len(events))
    return result
