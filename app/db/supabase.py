import asyncio
import time

import structlog
from supabase import AsyncClient, acreate_client

from app.config import settings

SAVE_TIMEOUT_SECONDS = 10
_RECONNECT_BACKOFF_BASE = 1.0
_RECONNECT_BACKOFF_MAX = 60.0

logger = structlog.get_logger()

_client: AsyncClient | None = None
_last_failure_time: float = 0.0
_consecutive_failures: int = 0


def _reset_client() -> None:
    """Reset the global client so the next call to get_client() creates a new one."""
    global _client, _last_failure_time, _consecutive_failures
    _client = None
    _last_failure_time = time.monotonic()
    _consecutive_failures += 1
    logger.warning(
        "supabase_client_reset",
        consecutive_failures=_consecutive_failures,
    )


async def get_client() -> AsyncClient:
    global _client, _consecutive_failures
    if _client is None:
        # Apply exponential backoff if we had recent failures
        if _consecutive_failures > 0:
            backoff = min(
                _RECONNECT_BACKOFF_BASE * (2 ** (_consecutive_failures - 1)),
                _RECONNECT_BACKOFF_MAX,
            )
            elapsed = time.monotonic() - _last_failure_time
            if elapsed < backoff:
                raise ConnectionError(
                    f"Supabase reconnect backoff: {backoff - elapsed:.1f}s remaining"
                )
        try:
            _client = await acreate_client(settings.supabase_url, settings.supabase_service_key)
            _consecutive_failures = 0
        except Exception:
            _reset_client()
            raise
    return _client


async def save_description(
    cog_image_id: str,
    coordinates: list[float],
    captured_at: str | None,
    location: dict | None,
    land_cover: dict | None,
    description: str | None,
    context: dict | None,
) -> dict | None:
    try:
        client = await get_client()
        row = {
            "cog_image_id": cog_image_id,
            "coordinates": coordinates,
            "captured_at": captured_at,
            "description": description,
        }
        if location:
            row.update(
                {
                    "country": location.get("country"),
                    "country_code": location.get("country_code"),
                    "region": location.get("region"),
                    "city": location.get("city"),
                    "place_name": location.get("place_name"),
                }
            )
        if land_cover:
            row["land_cover_json"] = land_cover.get("classes")
            row["land_cover_summary"] = land_cover.get("summary")
        if context:
            row["context_json"] = context.get("events")
            row["context_summary"] = context.get("summary")

        await asyncio.wait_for(
            client.table("image_descriptions").upsert(row, on_conflict="cog_image_id").execute(),
            timeout=SAVE_TIMEOUT_SECONDS,
        )
        logger.info("saved description to supabase", cog_image_id=cog_image_id)
        return True
    except TimeoutError:
        logger.error("supabase save timed out", cog_image_id=cog_image_id)
        return False
    except ConnectionError:
        raise
    except Exception as e:
        _reset_client()
        logger.error("supabase save failed", error=str(e))
        return False


async def ping() -> bool:
    try:
        client = await get_client()
        await asyncio.wait_for(
            client.table("image_descriptions").select("cog_image_id").limit(1).execute(),
            timeout=settings.timeout_supabase_ping,
        )
        return True
    except TimeoutError:
        logger.warning("supabase ping timed out", timeout=settings.timeout_supabase_ping)
        return False
    except Exception as e:
        _reset_client()
        logger.warning("supabase ping failed", error=str(e))
        return False


async def list_descriptions(
    offset: int = 0,
    limit: int = 20,
    created_after: str | None = None,
    created_before: str | None = None,
) -> dict:
    try:
        client = await get_client()
        query = client.table("image_descriptions").select("*", count="exact")
        if created_after:
            query = query.gte("created_at", created_after)
        if created_before:
            query = query.lte("created_at", created_before)
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = await query.execute()
        return {"items": result.data, "total": result.count or 0}
    except ConnectionError:
        raise
    except Exception as e:
        _reset_client()
        logger.error("supabase list failed", error=str(e))
        return {"items": [], "total": 0}


async def delete_description(cog_image_id: str) -> bool:
    try:
        client = await get_client()
        result = (
            await client.table("image_descriptions")
            .delete()
            .eq("cog_image_id", cog_image_id)
            .execute()
        )
        if not result.data:
            return False
        logger.info("deleted description from supabase", cog_image_id=cog_image_id)
        return True
    except ConnectionError:
        raise
    except Exception as e:
        _reset_client()
        logger.error("supabase delete failed", cog_image_id=cog_image_id, error=str(e))
        return False


async def get_description(cog_image_id: str) -> dict | None:
    try:
        client = await get_client()
        result = (
            await client.table("image_descriptions")
            .select("*")
            .eq("cog_image_id", cog_image_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except ConnectionError:
        raise
    except Exception as e:
        _reset_client()
        logger.error("supabase get failed", error=str(e))
        return None
