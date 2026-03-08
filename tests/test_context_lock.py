"""Tests for context module asyncio.Lock deduplication (#268)."""

import asyncio

import pytest

from app.cache.store import CacheStore
from app.modules.context import _context_locks, research_context


@pytest.fixture
async def cache(tmp_path):
    store = CacheStore(str(tmp_path / "test.db"))
    await store.init()
    yield store
    await store.close()


@pytest.fixture(autouse=True)
def _clear_locks():
    _context_locks.clear()
    yield
    _context_locks.clear()


async def test_concurrent_same_key_single_api_call(cache, httpx_mock):
    """동일 캐시 키로 동시 요청 시 외부 API가 1회만 호출되어야 한다."""
    httpx_mock.add_response(
        json={
            "RelatedTopics": [
                {"Text": "News item", "FirstURL": "https://example.com/1"},
            ]
        }
    )

    results = await asyncio.gather(
        research_context("서울", "2025-06-15", cache),
        research_context("서울", "2025-06-15", cache),
        research_context("서울", "2025-06-15", cache),
    )

    # 모든 결과가 동일해야 함
    for r in results:
        assert len(r.events) == 1

    # API는 1회만 호출 (나머지는 캐시 hit 또는 lock 대기 후 캐시 hit)
    assert len(httpx_mock.get_requests()) == 1


async def test_different_keys_independent(cache, httpx_mock):
    """다른 캐시 키는 독립적으로 API를 호출해야 한다."""
    httpx_mock.add_response(json={"RelatedTopics": []})
    httpx_mock.add_response(json={"RelatedTopics": []})

    await asyncio.gather(
        research_context("서울", "2025-06-15", cache),
        research_context("부산", "2025-07-15", cache),
    )

    assert len(httpx_mock.get_requests()) == 2
