import json
import time
from collections import defaultdict

import aiosqlite


class CacheStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._hits: dict[str, int] = defaultdict(int)
        self._misses: dict[str, int] = defaultdict(int)

    async def init(self):
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL
            )
        """)
        await self._db.commit()

    def _module_from_key(self, key: str) -> str:
        return key.split(":")[0] if ":" in key else "unknown"

    async def get(self, key: str) -> dict | None:
        module = self._module_from_key(key)
        async with self._db.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            self._misses[module] += 1
            return None
        value, expires_at = row
        if expires_at and time.time() > expires_at:
            await self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
            await self._db.commit()
            self._misses[module] += 1
            return None
        self._hits[module] += 1
        return json.loads(value)

    async def set(self, key: str, value: dict, ttl_days: int | None = None):
        expires_at = time.time() + ttl_days * 86400 if ttl_days else None
        await self._db.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), expires_at),
        )
        await self._db.commit()

    async def stats(self) -> dict:
        async with self._db.execute("SELECT COUNT(*) FROM cache") as cursor:
            row = await cursor.fetchone()
            entry_count = row[0]

        async with self._db.execute(
            "SELECT SUM(LENGTH(key) + LENGTH(value)) FROM cache"
        ) as cursor:
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

    async def close(self):
        if self._db:
            await self._db.close()
