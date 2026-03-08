import re

import structlog
from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = structlog.get_logger()

_RATE_LIMIT_PATTERN = re.compile(r"^\d+/(second|minute|hour|day)$")


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
    shutdown_batch_timeout: int = 60
    request_timeout: int = 30
    batch_concurrency: int = 3
    cache_ttl_seconds: int = 86400 * 30  # 30 days default
    cache_cleanup_interval_seconds: int = 3600
    gzip_min_size: int = 500
    service_name: str = "image-descriptor"
    environment: str = "production"
    timeout_geocoder: float = 10.0
    timeout_landcover: float = 15.0
    timeout_context: float = 10.0
    timeout_describer: float = 10.0
    timeout_mission: float = 10.0
    timeout_http_client: float = 10.0
    max_image_download_bytes: int = 5 * 1024 * 1024
    max_image_redirects: int = 5
    timeout_supabase_ping: float = 5.0

    @field_validator(
        "cache_ttl_seconds",
        "cache_cleanup_interval_seconds",
        "shutdown_timeout",
        "shutdown_batch_timeout",
        "request_timeout",
        "batch_concurrency",
        "thumbnail_max_pixels",
        "gzip_min_size",
        "timeout_geocoder",
        "timeout_landcover",
        "timeout_context",
        "timeout_describer",
        "timeout_mission",
        "timeout_http_client",
        "max_image_download_bytes",
        "max_image_redirects",
        "timeout_supabase_ping",
    )
    @classmethod
    def _positive_int(cls, v: int | float, info) -> int | float:
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive, got {v}")
        return v

    @field_validator(
        "rate_limit",
        "rate_limit_describe",
        "rate_limit_batch",
        "rate_limit_data",
        "rate_limit_read",
    )
    @classmethod
    def _valid_rate_limit(cls, v: str, info) -> str:
        if not _RATE_LIMIT_PATTERN.match(v):
            raise ValueError(
                f"{info.field_name} must match '<number>/<second|minute|hour|day>', got '{v}'"
            )
        return v

    @field_validator("cors_origins")
    @classmethod
    def _valid_cors_origins(cls, v: str) -> str:
        for origin in v.split():
            origin = origin.strip()
            if not origin:
                continue
            if not re.match(r"^https?://", origin):
                raise ValueError(
                    f"Each CORS origin must start with http:// or https://, got '{origin}'"
                )
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [s.strip() for s in self.cors_origins.split() if s.strip()]

    def log_settings_summary(self) -> None:
        def _mask(value: str) -> str:
            if len(value) <= 8:
                return "***"
            return value[:4] + "***" + value[-4:]

        logger.info(
            "settings_summary",
            supabase_url=self.supabase_url,
            google_ai_api_key=_mask(self.google_ai_api_key),
            supabase_service_key=_mask(self.supabase_service_key),
            api_key=_mask(self.api_key),
            nominatim_url=self.nominatim_url,
            overpass_url=self.overpass_url,
            cors_origins=self.cors_origins_list,
            log_level=self.log_level,
            cache_db_path=self.cache_db_path,
            cache_ttl_seconds=self.cache_ttl_seconds,
            cache_cleanup_interval_seconds=self.cache_cleanup_interval_seconds,
            thumbnail_max_pixels=self.thumbnail_max_pixels,
            rate_limit=self.rate_limit,
            rate_limit_describe=self.rate_limit_describe,
            rate_limit_batch=self.rate_limit_batch,
            rate_limit_data=self.rate_limit_data,
            rate_limit_read=self.rate_limit_read,
            shutdown_timeout=self.shutdown_timeout,
            shutdown_batch_timeout=self.shutdown_batch_timeout,
            request_timeout=self.request_timeout,
            batch_concurrency=self.batch_concurrency,
            gzip_min_size=self.gzip_min_size,
            timeout_geocoder=self.timeout_geocoder,
            timeout_landcover=self.timeout_landcover,
            timeout_context=self.timeout_context,
            timeout_describer=self.timeout_describer,
            timeout_mission=self.timeout_mission,
            timeout_http_client=self.timeout_http_client,
            max_image_download_bytes=self.max_image_download_bytes,
            max_image_redirects=self.max_image_redirects,
            timeout_supabase_ping=self.timeout_supabase_ping,
        )

    model_config = {"env_file": ".env"}


settings = Settings()
