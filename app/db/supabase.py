import asyncio

import structlog
from supabase import AsyncClient, acreate_client

from app.config import settings

SAVE_TIMEOUT_SECONDS = 10

logger = structlog.get_logger()

_client: AsyncClient | None = None


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = await acreate_client(settings.supabase_url, settings.supabase_service_key)
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
    except Exception as e:
        logger.error("supabase save failed", error=str(e))
        return False


async def ping() -> bool:
    try:
        client = await get_client()
        await client.table("image_descriptions").select("cog_image_id").limit(1).execute()
        return True
    except Exception as e:
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
    except Exception as e:
        logger.error("supabase list failed", error=str(e))
        return {"items": [], "total": 0}


async def delete_description(cog_image_id: str) -> bool:
    client = await get_client()
    result = (
        await client.table("image_descriptions").delete().eq("cog_image_id", cog_image_id).execute()
    )
    if not result.data:
        return False
    logger.info("deleted description from supabase", cog_image_id=cog_image_id)
    return True


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
    except Exception as e:
        logger.error("supabase get failed", error=str(e))
        return None
