import structlog
from supabase import AsyncClient, acreate_client

from app.config import settings

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
            row.update({
                "country": location.get("country"),
                "country_code": location.get("country_code"),
                "region": location.get("region"),
                "city": location.get("city"),
                "place_name": location.get("place_name"),
            })
        if land_cover:
            row["land_cover_json"] = land_cover.get("classes")
            row["land_cover_summary"] = land_cover.get("summary")
        if context:
            row["context_json"] = context.get("events")
            row["context_summary"] = context.get("summary")

        result = (
            await client.table("image_descriptions")
            .upsert(row, on_conflict="cog_image_id")
            .execute()
        )
        logger.info("saved description to supabase", cog_image_id=cog_image_id)
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error("supabase save failed", error=str(e))
        return None


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
