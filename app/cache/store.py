import json
import time

import aiosqlite


class CacheStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

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

    async def get(self, key: str) -> dict | None:
        async with self._db.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at and time.time() > expires_at:
            await self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
            await self._db.commit()
            return None
        return json.loads(value)

    async def set(self, key: str, value: dict, ttl_days: int | None = None):
        expires_at = time.time() + ttl_days * 86400 if ttl_days else None
        await self._db.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), expires_at),
        )
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
