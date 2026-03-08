import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings


def _make_env(**overrides):
    base = {
        "GOOGLE_AI_API_KEY": "test-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_SERVICE_KEY": "test-service-key",
        "API_KEY": "test-api-key",
    }
    base.update(overrides)
    return base


class TestRequiredFields:
    def test_valid_settings(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.google_ai_api_key == "test-key"
            assert s.supabase_url == "https://test.supabase.co"

    def test_missing_google_ai_api_key(self):
        env = _make_env()
        del env["GOOGLE_AI_API_KEY"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
            Settings()

    def test_missing_supabase_url(self):
        env = _make_env()
        del env["SUPABASE_URL"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
            Settings()

    def test_missing_supabase_service_key(self):
        env = _make_env()
        del env["SUPABASE_SERVICE_KEY"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
            Settings()

    def test_missing_api_key(self):
        env = _make_env()
        del env["API_KEY"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
            Settings()


class TestDefaults:
    def test_default_log_level(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.log_level == "INFO"

    def test_default_thumbnail_max_pixels(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.thumbnail_max_pixels == 768

    def test_default_rate_limit(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.rate_limit == "30/minute"


class TestCorsOrigins:
    def test_cors_origins_list_default(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.cors_origins_list == ["http://localhost:5173", "http://localhost:3000"]

    def test_cors_origins_list_custom(self):
        env = _make_env(CORS_ORIGINS="https://a.com https://b.com")
        with patch.dict(os.environ, env, clear=True):
            s = Settings()
            assert s.cors_origins_list == ["https://a.com", "https://b.com"]

    def test_cors_origins_single(self):
        with patch.dict(os.environ, _make_env(CORS_ORIGINS="https://only.com"), clear=True):
            s = Settings()
            assert s.cors_origins_list == ["https://only.com"]


class TestCacheSettings:
    def test_default_cache_ttl_seconds(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.cache_ttl_seconds == 86400 * 30

    def test_default_cache_cleanup_interval(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.cache_cleanup_interval_seconds == 3600

    def test_custom_cache_ttl_seconds(self):
        with patch.dict(os.environ, _make_env(CACHE_TTL_SECONDS="7200"), clear=True):
            s = Settings()
            assert s.cache_ttl_seconds == 7200

    def test_custom_cache_cleanup_interval(self):
        with patch.dict(os.environ, _make_env(CACHE_CLEANUP_INTERVAL_SECONDS="1800"), clear=True):
            s = Settings()
            assert s.cache_cleanup_interval_seconds == 1800


class TestOverrides:
    def test_custom_log_level(self):
        with patch.dict(os.environ, _make_env(LOG_LEVEL="DEBUG"), clear=True):
            s = Settings()
            assert s.log_level == "DEBUG"

    def test_custom_thumbnail_max_pixels(self):
        with patch.dict(os.environ, _make_env(THUMBNAIL_MAX_PIXELS="512"), clear=True):
            s = Settings()
            assert s.thumbnail_max_pixels == 512

    def test_invalid_thumbnail_max_pixels(self):
        with patch.dict(os.environ, _make_env(THUMBNAIL_MAX_PIXELS="not_a_number"), clear=True):
            with pytest.raises(ValidationError):
                Settings()


class TestExternalizedConstants:
    def test_default_jwks_ttl(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.jwks_ttl_seconds == 3600.0

    def test_default_supabase_save_timeout(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.supabase_save_timeout == 10.0

    def test_default_supabase_reconnect_backoff(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.supabase_reconnect_backoff_base == 1.0
            assert s.supabase_reconnect_backoff_max == 60.0

    def test_default_health_timeout(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.health_timeout == 3.0

    def test_default_cache_cleanup_poll_interval(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.cache_cleanup_poll_interval == 0.5

    def test_default_overpass_timeout(self):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            assert s.overpass_timeout == 10

    def test_custom_jwks_ttl(self):
        with patch.dict(os.environ, _make_env(JWKS_TTL_SECONDS="1800"), clear=True):
            s = Settings()
            assert s.jwks_ttl_seconds == 1800.0

    def test_custom_supabase_save_timeout(self):
        with patch.dict(os.environ, _make_env(SUPABASE_SAVE_TIMEOUT="30"), clear=True):
            s = Settings()
            assert s.supabase_save_timeout == 30.0

    def test_custom_overpass_timeout(self):
        with patch.dict(os.environ, _make_env(OVERPASS_TIMEOUT="20"), clear=True):
            s = Settings()
            assert s.overpass_timeout == 20


class TestPositiveIntValidation:
    @pytest.mark.parametrize(
        "field",
        [
            "CACHE_TTL_SECONDS",
            "CACHE_CLEANUP_INTERVAL_SECONDS",
            "SHUTDOWN_TIMEOUT",
            "REQUEST_TIMEOUT",
            "BATCH_CONCURRENCY",
            "THUMBNAIL_MAX_PIXELS",
            "GZIP_MIN_SIZE",
            "JWKS_TTL_SECONDS",
            "SUPABASE_SAVE_TIMEOUT",
            "SUPABASE_RECONNECT_BACKOFF_BASE",
            "SUPABASE_RECONNECT_BACKOFF_MAX",
            "HEALTH_TIMEOUT",
            "CACHE_CLEANUP_POLL_INTERVAL",
            "OVERPASS_TIMEOUT",
        ],
    )
    def test_zero_rejected(self, field):
        with patch.dict(os.environ, _make_env(**{field: "0"}), clear=True):
            with pytest.raises(ValidationError, match="must be positive"):
                Settings()

    @pytest.mark.parametrize(
        "field",
        [
            "CACHE_TTL_SECONDS",
            "SHUTDOWN_TIMEOUT",
            "BATCH_CONCURRENCY",
        ],
    )
    def test_negative_rejected(self, field):
        with patch.dict(os.environ, _make_env(**{field: "-1"}), clear=True):
            with pytest.raises(ValidationError, match="must be positive"):
                Settings()


class TestRateLimitValidation:
    @pytest.mark.parametrize(
        "value",
        ["10/minute", "5/second", "100/hour", "1000/day"],
    )
    def test_valid_rate_limit_formats(self, value):
        with patch.dict(os.environ, _make_env(RATE_LIMIT=value), clear=True):
            s = Settings()
            assert s.rate_limit == value

    @pytest.mark.parametrize(
        "value",
        ["abc", "10/weekly", "10", "/minute", "10/"],
    )
    def test_invalid_rate_limit_rejected(self, value):
        with patch.dict(os.environ, _make_env(RATE_LIMIT=value), clear=True):
            with pytest.raises(ValidationError, match="must match"):
                Settings()


class TestCorsOriginsValidation:
    def test_invalid_cors_origin_no_scheme(self):
        with patch.dict(os.environ, _make_env(CORS_ORIGINS="example.com"), clear=True):
            with pytest.raises(ValidationError, match="http://"):
                Settings()

    def test_valid_cors_origins(self):
        env = _make_env(CORS_ORIGINS="https://a.com http://localhost:3000")
        with patch.dict(os.environ, env, clear=True):
            s = Settings()
            assert len(s.cors_origins_list) == 2


class TestSettingsLogSummary:
    def test_log_settings_summary_masks_keys(self, capsys):
        with patch.dict(os.environ, _make_env(), clear=True):
            s = Settings()
            s.log_settings_summary()
