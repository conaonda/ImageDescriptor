import pytest

from app.cache.store import CacheStore
from app.modules.context import research_context


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


async def test_context_with_results(cache, httpx_mock):
    httpx_mock.add_response(
        url="https://api.duckduckgo.com/?q=%EC%84%9C%EC%9A%B8+2025-06&format=json&no_html=1",
        json={
            "RelatedTopics": [
                {"Text": "서울 관련 뉴스 1", "FirstURL": "https://example.com/1"},
                {"Text": "서울 관련 뉴스 2", "FirstURL": "https://example.com/2"},
            ],
        },
    )

    result = await research_context("서울", "2025-06-15", cache)
    assert len(result.events) == 2
    assert result.events[0].title == "서울 관련 뉴스 1"
    assert "2건" in result.summary


async def test_context_empty_results(cache, httpx_mock):
    httpx_mock.add_response(json={"RelatedTopics": []})

    result = await research_context("태평양", "2025-06-15", cache)
    assert len(result.events) == 0
    assert "찾지 못했습니다" in result.summary


async def test_context_cache_hit(cache, httpx_mock):
    httpx_mock.add_response(
        json={
            "RelatedTopics": [
                {"Text": "News", "FirstURL": "https://example.com"},
            ]
        }
    )

    await research_context("서울", "2025-06-15", cache)
    result = await research_context("서울", "2025-06-15", cache)
    assert len(result.events) == 1
    assert len(httpx_mock.get_requests()) == 1


async def test_context_api_failure(cache, httpx_mock):
    httpx_mock.add_exception(Exception("Network error"))

    result = await research_context("서울", "2025-06-15", cache)
    assert len(result.events) == 0
    assert "찾지 못했습니다" in result.summary
