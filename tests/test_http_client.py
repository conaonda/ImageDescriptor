"""Tests for shared httpx client module (#225, #249)."""

import asyncio

import httpx
import pytest

import app.http_client as http_client_mod
from app.http_client import close_client, get_client


@pytest.fixture(autouse=True)
async def _reset_client():
    """Reset the global client before and after each test."""
    http_client_mod._client = None
    http_client_mod._lock = None
    yield
    if http_client_mod._client is not None and not http_client_mod._client.is_closed:
        await http_client_mod._client.aclose()
    http_client_mod._client = None
    http_client_mod._lock = None


async def test_get_client_returns_async_client():
    client = await get_client()
    assert isinstance(client, httpx.AsyncClient)


async def test_get_client_returns_same_instance():
    client1 = await get_client()
    client2 = await get_client()
    assert client1 is client2


async def test_close_client():
    client = await get_client()
    assert not client.is_closed
    await close_client()
    assert client.is_closed


async def test_get_client_after_close():
    client1 = await get_client()
    await close_client()
    client2 = await get_client()
    assert not client2.is_closed
    assert client1 is not client2


async def test_concurrent_get_client_returns_single_instance():
    """#249: Concurrent calls should produce only one client instance."""
    results = await asyncio.gather(*(get_client() for _ in range(10)))
    assert all(r is results[0] for r in results)
