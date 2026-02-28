from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_ai_api_key: str
    supabase_url: str
    supabase_service_key: str
    api_key: str

    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    cache_db_path: str = "./cache.db"
    log_level: str = "INFO"
    thumbnail_max_pixels: int = 768

    @property
    def cors_origins_list(self) -> list[str]:
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]

    model_config = {"env_file": ".env"}


settings = Settings()
