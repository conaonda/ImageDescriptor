import base64

import structlog
from google import genai

from app.cache.store import CacheStore
from app.config import settings

logger = structlog.get_logger()


def _make_prompt(place_name: str, captured_at: str, land_cover_summary: str) -> str:
    return f"""이 위성영상을 분석해주세요.
위치: {place_name}
촬영일자: {captured_at}
피복분류: {land_cover_summary}

다음을 포함하여 2-3문장으로 설명해주세요:
1. 영상에서 관찰되는 주요 지형/지물
2. 영상의 특이사항이나 주목할 점
3. 이 영상이 흥미로운 이유

한국어로 작성해주세요."""


async def describe_image(
    thumbnail: str,
    place_name: str,
    captured_at: str,
    land_cover_summary: str,
    cache: CacheStore,
    cog_image_id: str | None = None,
) -> str:
    if cog_image_id:
        cache_key = f"describe:{cog_image_id}"
        cached = await cache.get(cache_key)
        if cached:
            logger.debug("describer cache hit", cog_image_id=cog_image_id)
            return cached["description"]

    # 썸네일 데이터 준비
    if thumbnail.startswith("data:image"):
        # data:image/png;base64,xxxx → base64 부분 추출
        b64_data = thumbnail.split(",", 1)[1]
        image_bytes = base64.b64decode(b64_data)
    elif thumbnail.startswith("http"):
        # URL인 경우 다운로드
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(thumbnail, timeout=10.0)
            resp.raise_for_status()
            image_bytes = resp.content
    else:
        image_bytes = base64.b64decode(thumbnail)

    prompt = _make_prompt(place_name, captured_at, land_cover_summary)

    client = genai.Client(api_key=settings.google_ai_api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            prompt,
        ],
    )

    description = response.text.strip()

    if cog_image_id:
        await cache.set(f"describe:{cog_image_id}", {"description": description})

    logger.info("describer result", description_length=len(description))
    return description
