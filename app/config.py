from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_ai_api_key: str
    supabase_url: str
    supabase_service_key: str
    api_key: str

    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    cors_origins: str = "http://localhost:5173 http://localhost:3000"
    cache_db_path: str = "./cache.db"
    log_level: str = "INFO"
    thumbnail_max_pixels: int = 768
    rate_limit: str = "30/minute"
    rate_limit_describe: str = "20/minute"
    rate_limit_batch: str = "10/minute"
    rate_limit_data: str = "30/minute"
    rate_limit_read: str = "60/minute"
    shutdown_timeout: int = 30
    request_timeout: int = 30
    batch_concurrency: int = 3
    cache_ttl_seconds: int = 86400 * 30  # 30 days default
    cache_cleanup_interval_seconds: int = 3600
    gzip_min_size: int = 500

    @property
    def cors_origins_list(self) -> list[str]:
        return [s.strip() for s in self.cors_origins.split() if s.strip()]

    model_config = {"env_file": ".env"}


settings = Settings()
