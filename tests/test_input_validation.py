"""Tests for #229 captured_at / cog_image_id validation and #231 timeout settings."""

import pytest
from pydantic import ValidationError

from app.api.schemas import _COG_IMAGE_ID_MAX_LENGTH, BatchDescribeItem, DescribeRequest


class TestCapturedAtValidation:
    def _make(self, captured_at):
        return DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
            captured_at=captured_at,
        )

    def test_none_is_allowed(self):
        req = self._make(None)
        assert req.captured_at is None

    def test_date_only(self):
        req = self._make("2025-01-15")
        assert req.captured_at == "2025-01-15"

    def test_datetime_with_tz(self):
        req = self._make("2025-01-15T10:30:00Z")
        assert req.captured_at == "2025-01-15T10:30:00Z"

    def test_datetime_with_offset(self):
        req = self._make("2025-01-15T10:30:00+09:00")
        assert req.captured_at == "2025-01-15T10:30:00+09:00"

    def test_datetime_without_tz(self):
        req = self._make("2025-01-15T10:30:00")
        assert req.captured_at == "2025-01-15T10:30:00"

    def test_invalid_format_rejected(self):
        with pytest.raises(ValidationError, match="ISO 8601"):
            self._make("15/01/2025")

    def test_invalid_date_rejected(self):
        with pytest.raises(ValidationError, match="not a valid date"):
            self._make("2025-13-45")

    def test_random_string_rejected(self):
        with pytest.raises(ValidationError, match="ISO 8601"):
            self._make("yesterday")

    def test_batch_item_valid(self):
        item = BatchDescribeItem(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
            captured_at="2025-06-15",
        )
        assert item.captured_at == "2025-06-15"

    def test_batch_item_invalid(self):
        with pytest.raises(ValidationError, match="ISO 8601"):
            BatchDescribeItem(
                thumbnail="dGVzdA==",
                coordinates=[126.978, 37.566],
                captured_at="not-a-date",
            )


class TestCogImageIdValidation:
    def test_valid_uuid(self):
        req = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
            cog_image_id="550e8400-e29b-41d4-a716-446655440000",
        )
        assert req.cog_image_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_none_is_allowed(self):
        req = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
        )
        assert req.cog_image_id is None

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError, match="string_too_long"):
            DescribeRequest(
                thumbnail="dGVzdA==",
                coordinates=[126.978, 37.566],
                cog_image_id="x" * (_COG_IMAGE_ID_MAX_LENGTH + 1),
            )

    def test_max_length_accepted(self):
        req = DescribeRequest(
            thumbnail="dGVzdA==",
            coordinates=[126.978, 37.566],
            cog_image_id="x" * _COG_IMAGE_ID_MAX_LENGTH,
        )
        assert len(req.cog_image_id) == _COG_IMAGE_ID_MAX_LENGTH

    def test_batch_item_too_long(self):
        with pytest.raises(ValidationError, match="string_too_long"):
            BatchDescribeItem(
                thumbnail="dGVzdA==",
                coordinates=[126.978, 37.566],
                cog_image_id="x" * (_COG_IMAGE_ID_MAX_LENGTH + 1),
            )


class TestTimeoutSettings:
    def test_default_timeout_values(self):
        from app.config import settings

        assert settings.timeout_geocoder == 10.0
        assert settings.timeout_landcover == 15.0
        assert settings.timeout_context == 10.0
        assert settings.timeout_describer == 10.0
        assert settings.timeout_http_client == 10.0
