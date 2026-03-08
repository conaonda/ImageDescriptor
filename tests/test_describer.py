import base64
import io
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.cache.store import CacheStore
from app.modules.describer import (
    _download_image,
    _is_blocked_ip,
    _make_prompt,
    _resize_for_gemini,
    _validate_host_ips,
    _validate_thumbnail_url,
    describe_image,
)


def test_make_prompt():
    prompt = _make_prompt("서울", "2025-06-15", "주거지역 50%")
    assert "서울" in prompt
    assert "2025-06-15" in prompt
    assert "주거지역 50%" in prompt
    assert "한국어" in prompt


def test_make_prompt_with_bbox():
    bbox = [126.0, 37.0, 127.0, 38.0]
    prompt = _make_prompt("서울", "2025-06-15", "주거지역 50%", bbox=bbox)
    assert "km" in prompt
    assert "영상 범위" in prompt


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


@patch("app.modules.describer._resize_for_gemini", return_value=b"resized")
@patch("app.modules.describer.genai")
async def test_describe_image(mock_genai, _mock_resize, cache):
    mock_response = MagicMock()
    mock_response.text = "  서울 도심의 위성영상입니다.  "

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_genai.Client.return_value = mock_client

    thumbnail = base64.b64encode(b"fake-image-data").decode()
    result = await describe_image(thumbnail, "서울특별시", "2025-06-15", "주거지역 50%", cache)

    description, cached = result
    assert description == "서울 도심의 위성영상입니다."
    assert cached is False
    mock_client.models.generate_content.assert_called_once()


@patch("app.modules.describer.genai")
async def test_describe_image_cache_hit(mock_genai, cache):
    # Pre-populate cache
    await cache.set("describe:test-id", {"description": "cached description"})

    result = await describe_image(
        "dGVzdA==", "서울", "2025-06-15", "summary", cache, cog_image_id="test-id"
    )

    description, cached = result
    assert description == "cached description"
    assert cached is True
    mock_genai.Client.assert_not_called()


@patch("app.modules.describer.socket.getaddrinfo")
def test_validate_thumbnail_url_blocks_metadata_ip(mock_dns):
    mock_dns.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]
    with pytest.raises(ValueError, match="blocked IP"):
        _validate_thumbnail_url("http://metadata.google.internal/")


@patch("app.modules.describer.socket.getaddrinfo")
def test_validate_thumbnail_url_blocks_private_ip(mock_dns):
    mock_dns.return_value = [(2, 1, 6, "", ("192.168.1.1", 0))]
    with pytest.raises(ValueError, match="blocked IP"):
        _validate_thumbnail_url("http://internal-server.local/image.png")


@patch("app.modules.describer.socket.getaddrinfo")
def test_validate_thumbnail_url_allows_public_ip(mock_dns):
    mock_dns.return_value = [(2, 1, 6, "", ("142.250.196.110", 0))]
    _validate_thumbnail_url("https://example.com/image.png")


@patch("app.modules.describer.socket.getaddrinfo")
def test_validate_thumbnail_url_blocks_ipv6_loopback(mock_dns):
    mock_dns.return_value = [(10, 1, 6, "", ("::1", 0, 0, 0))]
    with pytest.raises(ValueError, match="blocked IP"):
        _validate_thumbnail_url("http://evil.com/image.png")


@patch("app.modules.describer.socket.getaddrinfo")
def test_validate_thumbnail_url_blocks_multicast(mock_dns):
    mock_dns.return_value = [(2, 1, 6, "", ("224.0.0.1", 0))]
    with pytest.raises(ValueError, match="blocked IP"):
        _validate_thumbnail_url("http://multicast.example.com/image.png")


def test_is_blocked_ip_multicast():
    import ipaddress

    assert _is_blocked_ip(ipaddress.ip_address("224.0.0.1")) is True
    assert _is_blocked_ip(ipaddress.ip_address("ff02::1")) is True


def test_is_blocked_ip_allows_public():
    import ipaddress

    assert _is_blocked_ip(ipaddress.ip_address("8.8.8.8")) is False
    assert _is_blocked_ip(ipaddress.ip_address("2607:f8b0:4004:800::200e")) is False


@pytest.mark.parametrize("mode", ["RGBA", "P", "LA"])
def test_resize_for_gemini_converts_non_rgb_to_rgb(mode):
    """Non-RGB images should be converted to RGB JPEG without error."""
    img = Image.new(mode, (100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = _resize_for_gemini(buf.getvalue(), 200)
    output = Image.open(io.BytesIO(result))
    assert output.mode == "RGB"
    assert output.format == "JPEG"


def test_resize_for_gemini_downscales_large_image():
    """Images larger than max_size should be resized."""
    img = Image.new("RGB", (2000, 1500))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = _resize_for_gemini(buf.getvalue(), 500)
    output = Image.open(io.BytesIO(result))
    assert max(output.size) <= 500


@patch("app.modules.describer.socket.getaddrinfo", side_effect=socket.gaierror("DNS failed"))
def test_validate_host_ips_dns_failure(mock_dns):
    with pytest.raises(ValueError, match="DNS resolution failed"):
        _validate_host_ips("nonexistent.example.com")


def test_validate_thumbnail_url_no_hostname():
    with pytest.raises(ValueError, match="no hostname"):
        _validate_thumbnail_url("not-a-url")


@patch("app.modules.describer._resize_for_gemini", return_value=b"resized")
@patch("app.modules.describer.genai")
async def test_describe_image_data_uri(mock_genai, _mock_resize, cache):
    """data:image/... URI should be handled."""
    mock_response = MagicMock()
    mock_response.text = "  설명 텍스트  "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_genai.Client.return_value = mock_client

    img = Image.new("RGB", (10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    data_uri = f"data:image/png;base64,{b64}"

    desc, cached = await describe_image(data_uri, "서울", "2025-01-01", "summary", cache)
    assert desc == "설명 텍스트"
    assert cached is False


@patch("app.modules.describer._resize_for_gemini", return_value=b"resized")
@patch("app.modules.describer._download_image", new_callable=AsyncMock, return_value=b"image-data")
@patch("app.modules.describer._validate_thumbnail_url")
@patch("app.modules.describer.genai")
async def test_describe_image_url_thumbnail(
    mock_genai,
    _mock_validate,
    _mock_download,
    _mock_resize,
    cache,
):
    """HTTP URL thumbnails should be downloaded and described."""
    mock_response = MagicMock()
    mock_response.text = "  URL 영상 설명  "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_genai.Client.return_value = mock_client

    desc, cached = await describe_image(
        "https://example.com/image.jpg", "서울", "2025-01-01", "summary", cache
    )
    assert desc == "URL 영상 설명"
    _mock_validate.assert_called_once_with("https://example.com/image.jpg")
    _mock_download.assert_awaited_once()


@patch("app.modules.describer._resize_for_gemini", return_value=b"resized")
@patch("app.modules.describer.genai")
async def test_describe_image_caches_result(mock_genai, _mock_resize, cache):
    """Result should be cached when cog_image_id is provided."""
    mock_response = MagicMock()
    mock_response.text = "  캐시 테스트  "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_genai.Client.return_value = mock_client

    desc, cached = await describe_image(
        "dGVzdA==", "서울", "2025-01-01", "summary", cache, cog_image_id="cache-test-id"
    )
    assert cached is False

    # Verify it was cached
    stored = await cache.get("describe:cache-test-id")
    assert stored is not None
    assert stored["description"] == "캐시 테스트"


async def test_download_image_success(httpx_mock):
    """Successful image download."""
    httpx_mock.add_response(url="https://example.com/img.jpg", content=b"image-bytes")
    result = await _download_image("https://example.com/img.jpg")
    assert result == b"image-bytes"


async def test_download_image_content_length_too_large(httpx_mock):
    """Reject images when Content-Length exceeds limit."""
    httpx_mock.add_response(
        url="https://example.com/big.jpg",
        headers={"content-length": "10000000"},
        content=b"x",
    )
    with pytest.raises(ValueError, match="Image too large"):
        await _download_image("https://example.com/big.jpg")


class TestBase64Validation:
    """Tests for #224: Base64 thumbnail input validation."""

    async def test_invalid_base64_raises_value_error(self):
        cache = AsyncMock(spec=CacheStore)
        cache.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Invalid thumbnail data"):
            await describe_image(
                thumbnail="not-valid-base64!!!",
                place_name="서울",
                captured_at="2025-01-01",
                land_cover_summary="주거지역",
                cache=cache,
            )

    async def test_data_uri_missing_comma_raises_value_error(self):
        cache = AsyncMock(spec=CacheStore)
        cache.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Invalid thumbnail data"):
            await describe_image(
                thumbnail="data:image/png;base64NO_COMMA_HERE",
                place_name="서울",
                captured_at="2025-01-01",
                land_cover_summary="주거지역",
                cache=cache,
            )

    async def test_data_uri_with_invalid_base64_raises_value_error(self):
        cache = AsyncMock(spec=CacheStore)
        cache.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Invalid thumbnail data"):
            await describe_image(
                thumbnail="data:image/png;base64,NOT_VALID_BASE64!@#$",
                place_name="서울",
                captured_at="2025-01-01",
                land_cover_summary="주거지역",
                cache=cache,
            )
