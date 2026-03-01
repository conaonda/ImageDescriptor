import base64
import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.cache.store import CacheStore
from app.modules.describer import (
    _make_prompt,
    _resize_for_gemini,
    _validate_thumbnail_url,
    describe_image,
)


def test_make_prompt():
    prompt = _make_prompt("서울", "2025-06-15", "주거지역 50%")
    assert "서울" in prompt
    assert "2025-06-15" in prompt
    assert "주거지역 50%" in prompt
    assert "한국어" in prompt


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

    assert result == "서울 도심의 위성영상입니다."
    mock_client.models.generate_content.assert_called_once()


@patch("app.modules.describer.genai")
async def test_describe_image_cache_hit(mock_genai, cache):
    # Pre-populate cache
    await cache.set("describe:test-id", {"description": "cached description"})

    result = await describe_image(
        "dGVzdA==", "서울", "2025-06-15", "summary", cache, cog_image_id="test-id"
    )

    assert result == "cached description"
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


def test_resize_for_gemini_rgba_to_rgb():
    """RGBA PNG should be converted to RGB JPEG without error."""
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = _resize_for_gemini(buf.getvalue(), 200)
    output = Image.open(io.BytesIO(result))
    assert output.mode == "RGB"
    assert output.format == "JPEG"
