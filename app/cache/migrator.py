"""Lightweight schema migration runner for the cache SQLite database."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import aiosqlite
import structlog

logger = structlog.get_logger()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_MIGRATION_PATTERN = re.compile(r"^(\d{3})_.+\.py$")


async def _ensure_schema_version_table(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    await db.commit()


async def _get_applied_versions(db: aiosqlite.Connection) -> set[int]:
    async with db.execute("SELECT version FROM schema_version") as cur:
        rows = await cur.fetchall()
    return {row[0] for row in rows}


def _discover_migrations() -> list[tuple[int, str, str]]:
    """Return sorted list of (version, name, module_path)."""
    results: list[tuple[int, str, str]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        m = _MIGRATION_PATTERN.match(path.name)
        if m:
            version = int(m.group(1))
            name = path.stem
            module_path = f"app.cache.migrations.{name}"
            results.append((version, name, module_path))
    return results


async def run_migrations(db: aiosqlite.Connection) -> int:
    """Run all pending migrations. Returns the number of migrations applied."""
    await _ensure_schema_version_table(db)
    applied = await _get_applied_versions(db)
    migrations = _discover_migrations()

    count = 0
    for version, name, module_path in migrations:
        if version in applied:
            continue
        mod = importlib.import_module(module_path)
        sql_up = getattr(mod, "SQL_UP")
        await db.executescript(sql_up)
        await db.execute(
            "INSERT INTO schema_version (version, name) VALUES (?, ?)",
            (version, name),
        )
        await db.commit()
        logger.info("migration_applied", version=version, name=name)
        count += 1

    if count:
        logger.info("migrations_complete", applied=count)
    return count
