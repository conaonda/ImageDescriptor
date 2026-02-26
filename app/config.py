from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_ai_api_key: str
    supabase_url: str
    supabase_service_key: str
    api_key: str

    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    cache_db_path: str = "./cache.db"
    log_level: str = "INFO"

    model_config = {"env_file": ".env"}


settings = Settings()
