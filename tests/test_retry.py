"""Tests for retry logic on external API calls."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.utils.retry import _is_retryable, retry_gemini, retry_http


class TestIsRetryable:
    def test_connect_error_is_retryable(self):
        assert _is_retryable(httpx.ConnectError("connection refused"))

    def test_read_timeout_is_retryable(self):
        assert _is_retryable(httpx.ReadTimeout("timed out"))

    def test_connect_timeout_is_retryable(self):
        assert _is_retryable(httpx.ConnectTimeout("timed out"))

    def test_http_429_is_retryable(self):
        response = MagicMock(status_code=429)
        exc = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=response)
        assert _is_retryable(exc)

    def test_http_502_is_retryable(self):
        response = MagicMock(status_code=502)
        exc = httpx.HTTPStatusError("bad gateway", request=MagicMock(), response=response)
        assert _is_retryable(exc)

    def test_http_503_is_retryable(self):
        response = MagicMock(status_code=503)
        exc = httpx.HTTPStatusError("unavailable", request=MagicMock(), response=response)
        assert _is_retryable(exc)

    def test_http_400_not_retryable(self):
        response = MagicMock(status_code=400)
        exc = httpx.HTTPStatusError("bad request", request=MagicMock(), response=response)
        assert not _is_retryable(exc)

    def test_http_404_not_retryable(self):
        response = MagicMock(status_code=404)
        exc = httpx.HTTPStatusError("not found", request=MagicMock(), response=response)
        assert not _is_retryable(exc)

    def test_value_error_not_retryable(self):
        assert not _is_retryable(ValueError("bad input"))


class TestRetryHttp:
    async def test_succeeds_on_first_try(self):
        call_count = 0

        @retry_http
        async def fetch():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await fetch()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_transient_error(self):
        call_count = 0

        @retry_http
        async def fetch():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("connection refused")
            return "ok"

        result = await fetch()
        assert result == "ok"
        assert call_count == 3

    async def test_gives_up_after_max_attempts(self):
        call_count = 0

        @retry_http
        async def fetch():
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("connection refused")

        with pytest.raises(httpx.ConnectError):
            await fetch()
        assert call_count == 3  # stop_after_attempt(3)

    async def test_no_retry_on_client_error(self):
        call_count = 0

        @retry_http
        async def fetch():
            nonlocal call_count
            call_count += 1
            response = MagicMock(status_code=400)
            raise httpx.HTTPStatusError("bad request", request=MagicMock(), response=response)

        with pytest.raises(httpx.HTTPStatusError):
            await fetch()
        assert call_count == 1  # no retry for 400

    async def test_retries_on_429(self):
        call_count = 0

        @retry_http
        async def fetch():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                response = MagicMock(status_code=429)
                raise httpx.HTTPStatusError("rate limited", request=MagicMock(), response=response)
            return "ok"

        result = await fetch()
        assert result == "ok"
        assert call_count == 2


class TestRetryGemini:
    async def test_retries_any_exception(self):
        call_count = 0

        @retry_gemini
        async def call_api():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("API error")
            return "description"

        result = await call_api()
        assert result == "description"
        assert call_count == 3

    async def test_gives_up_after_max_attempts(self):
        call_count = 0

        @retry_gemini
        async def call_api():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("persistent error")

        with pytest.raises(RuntimeError):
            await call_api()
        assert call_count == 3
