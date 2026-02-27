import base64
from unittest.mock import MagicMock, patch

import pytest

from app.cache.store import CacheStore
from app.modules.describer import _make_prompt, describe_image


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


@patch("app.modules.describer.genai")
async def test_describe_image(mock_genai, cache):
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
