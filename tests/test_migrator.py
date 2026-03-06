"""Tests for cache DB migration runner."""

import aiosqlite
import pytest

from app.cache.migrator import (
    _discover_migrations,
    _ensure_schema_version_table,
    _get_applied_versions,
    run_migrations,
)


@pytest.fixture
async def db(tmp_path):
    async with aiosqlite.connect(str(tmp_path / "test.db")) as conn:
        yield conn


async def test_ensure_schema_version_table(db):
    await _ensure_schema_version_table(db)
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_get_applied_versions_empty(db):
    await _ensure_schema_version_table(db)
    versions = await _get_applied_versions(db)
    assert versions == set()


async def test_discover_migrations():
    migrations = _discover_migrations()
    assert len(migrations) >= 1
    assert migrations[0][0] == 1
    assert migrations[0][1] == "001_initial"


async def test_run_migrations_creates_cache_table(db):
    count = await run_migrations(db)
    assert count >= 1

    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cache'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None


async def test_run_migrations_idempotent(db):
    count1 = await run_migrations(db)
    assert count1 >= 1

    count2 = await run_migrations(db)
    assert count2 == 0


async def test_schema_version_recorded(db):
    await run_migrations(db)
    applied = await _get_applied_versions(db)
    assert 1 in applied


async def test_cache_store_uses_migrations(tmp_path):
    from app.cache.store import CacheStore

    store = CacheStore(str(tmp_path / "store.db"))
    await store.init()

    async with store._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None

    await store.close()
