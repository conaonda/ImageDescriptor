import base64
import io
import ipaddress
import socket
from urllib.parse import urlparse

import structlog
from google import genai
from PIL import Image

from app.cache.store import CacheStore
from app.config import settings

logger = structlog.get_logger()


def _validate_thumbnail_url(url: str) -> None:
    """Block SSRF: reject private/link-local IPs and validate after DNS resolution."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: no hostname")

    # Resolve DNS and check all resulting IPs
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for {hostname}") from e

    for family, _, _, _, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"URL resolves to blocked IP: {ip}")


def _resize_for_gemini(image_bytes: bytes, max_size: int) -> bytes:
    """Resize image to max_size px (longest edge) to reduce Gemini input tokens."""
    img = Image.open(io.BytesIO(image_bytes))
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


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
        # URL인 경우 다운로드 (최대 5MB)
        _validate_thumbnail_url(thumbnail)
        import httpx

        max_download = 5 * 1024 * 1024
        async with httpx.AsyncClient() as http_client:
            async with http_client.stream("GET", thumbnail, timeout=10.0) as resp:
                resp.raise_for_status()
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > max_download:
                    raise ValueError(
                        f"Image too large: {int(content_length)} bytes (max {max_download})"
                    )
                chunks = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > max_download:
                        raise ValueError(f"Image too large: >{max_download} bytes (max 5MB)")
                    chunks.append(chunk)
                image_bytes = b"".join(chunks)
    else:
        image_bytes = base64.b64decode(thumbnail)

    # Gemini 토큰 절감을 위해 이미지 리사이즈
    image_bytes = _resize_for_gemini(image_bytes, settings.thumbnail_max_pixels)

    prompt = _make_prompt(place_name, captured_at, land_cover_summary)

    client = genai.Client(api_key=settings.google_ai_api_key)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            genai.types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt,
        ],
        config={"max_output_tokens": 300},
    )

    description = response.text.strip()

    if cog_image_id:
        await cache.set(f"describe:{cog_image_id}", {"description": description})

    logger.info("describer result", description_length=len(description))
    return description
