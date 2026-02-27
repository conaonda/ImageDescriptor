from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_ai_api_key: str
    supabase_url: str
    supabase_service_key: str
    api_key: str

    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    cache_db_path: str = "./cache.db"
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [s.strip() for s in v.split(",") if s.strip()]
        return v

    model_config = {"env_file": ".env"}


settings = Settings()
