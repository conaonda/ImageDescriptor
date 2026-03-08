import json
import time
from collections import defaultdict

import aiosqlite
import structlog

from app.cache.migrator import run_migrations
from app.utils.metrics import cache_cleanup_total, cache_errors, cache_hits, cache_misses

logger = structlog.get_logger()


class CacheStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._hits: dict[str, int] = defaultdict(int)
        self._misses: dict[str, int] = defaultdict(int)

    async def init(self):
        self._db = await aiosqlite.connect(self._db_path)
        await run_migrations(self._db)

    def _module_from_key(self, key: str) -> str:
        return key.split(":")[0] if ":" in key else "unknown"

    async def get(self, key: str) -> dict | None:
        module = self._module_from_key(key)
        try:
            async with self._db.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
        except (aiosqlite.DatabaseError, OSError, ValueError) as e:
            logger.error("cache_get_error", key=key, error=str(e))
            cache_errors.labels(operation="get").inc()
            return None
        if row is None:
            self._misses[module] += 1
            cache_misses.labels(module=module).inc()
            return None
        value, expires_at = row
        if expires_at and time.time() > expires_at:
            try:
                await self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
                await self._db.commit()
            except (aiosqlite.DatabaseError, OSError, ValueError) as e:
                logger.warning("cache_expire_delete_error", key=key, error=str(e))
                cache_errors.labels(operation="delete").inc()
            self._misses[module] += 1
            cache_misses.labels(module=module).inc()
            return None
        self._hits[module] += 1
        cache_hits.labels(module=module).inc()
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error("cache_get_json_error", key=key, error=str(e))
            cache_errors.labels(operation="get").inc()
            return None

    async def set(
        self,
        key: str,
        value: dict,
        ttl_days: int | None = None,
        ttl_seconds: int | None = None,
    ):
        if ttl_seconds is not None:
            expires_at = time.time() + ttl_seconds
        elif ttl_days is not None:
            expires_at = time.time() + ttl_days * 86400
        else:
            expires_at = None
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), expires_at),
            )
            await self._db.commit()
        except (aiosqlite.DatabaseError, OSError, ValueError) as e:
            logger.warning("cache_set_error", key=key, error=str(e))
            cache_errors.labels(operation="set").inc()

    async def stats(self) -> dict:
        async with self._db.execute("SELECT COUNT(*) FROM cache") as cursor:
            row = await cursor.fetchone()
            entry_count = row[0]

        async with self._db.execute("SELECT SUM(LENGTH(key) + LENGTH(value)) FROM cache") as cursor:
            row = await cursor.fetchone()
            total_bytes = row[0] or 0

        modules = sorted(set(list(self._hits.keys()) + list(self._misses.keys())))
        per_module = {}
        for m in modules:
            hits = self._hits.get(m, 0)
            misses = self._misses.get(m, 0)
            total = hits + misses
            per_module[m] = {
                "hits": hits,
                "misses": misses,
                "hit_rate": round(hits / total, 4) if total > 0 else 0.0,
            }

        return {
            "entry_count": entry_count,
            "total_bytes": total_bytes,
            "modules": per_module,
        }

    async def ping(self) -> bool:
        try:
            async with self._db.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except (aiosqlite.DatabaseError, OSError, ValueError):
            return False

    async def cleanup_expired(self) -> int:
        now = time.time()
        try:
            async with self._db.execute(
                "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
            ) as cursor:
                deleted = cursor.rowcount
            await self._db.commit()
        except (aiosqlite.DatabaseError, OSError, ValueError) as e:
            logger.warning("cache_cleanup_error", error=str(e))
            cache_errors.labels(operation="cleanup").inc()
            return 0
        if deleted > 0:
            cache_cleanup_total.inc(deleted)
            logger.info("cache_cleanup", deleted=deleted)
        return deleted

    async def close(self):
        if self._db:
            await self._db.close()
