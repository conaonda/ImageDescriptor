"""Unit tests for CircuitBreaker and composer._safe_call error handling."""

import time

import pytest

from app.api.schemas import Warning
from app.utils.circuit_breaker import CircuitBreaker


class TestCircuitBreakerClosed:
    """Tests for normal (closed) circuit behavior."""

    async def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test")
        assert not await cb.is_open()

    async def test_stays_closed_after_success(self):
        cb = CircuitBreaker("test")
        await cb.record_success()
        assert not await cb.is_open()

    async def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        for _ in range(4):
            await cb.record_failure()
        assert not await cb.is_open()

    async def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_success()
        # After reset, 2 more failures should not open
        await cb.record_failure()
        await cb.record_failure()
        assert not await cb.is_open()


class TestCircuitBreakerOpen:
    """Tests for open circuit behavior."""

    async def test_opens_at_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3, cooldown_sec=10.0)
        for _ in range(3):
            await cb.record_failure()
        assert await cb.is_open()

    async def test_opens_exactly_at_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        await cb.record_failure()
        assert await cb.is_open()

    async def test_stays_open_during_cooldown(self):
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=100.0)
        await cb.record_failure()
        assert await cb.is_open()
        assert await cb.is_open()  # Still open on second check


class TestCircuitBreakerHalfOpen:
    """Tests for half-open state after cooldown expires."""

    async def test_resets_after_cooldown(self):
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=0.0)
        await cb.record_failure()
        # cooldown_sec=0 means it expires immediately
        assert not await cb.is_open()  # half-open → reset

    async def test_resets_with_short_cooldown(self):
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=0.05)
        await cb.record_failure()
        assert await cb.is_open()
        time.sleep(0.06)
        # After cooldown, should transition to half-open (closed)
        assert not await cb.is_open()

    async def test_reopens_on_failure_after_halfopen(self):
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=0.05)
        await cb.record_failure()
        assert await cb.is_open()
        time.sleep(0.06)
        # After cooldown, half-open reset
        assert not await cb.is_open()
        # Another failure should re-open
        await cb.record_failure()
        assert await cb.is_open()

    async def test_stays_closed_on_success_after_halfopen(self):
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=0.0)
        await cb.record_failure()
        assert not await cb.is_open()  # half-open reset
        await cb.record_success()
        assert not await cb.is_open()


class TestCircuitBreakerEdgeCases:
    """Edge cases and boundary tests."""

    async def test_multiple_successes_no_effect(self):
        cb = CircuitBreaker("test")
        for _ in range(100):
            await cb.record_success()
        assert not await cb.is_open()

    async def test_custom_parameters(self):
        cb = CircuitBreaker("custom", failure_threshold=2, cooldown_sec=60.0)
        await cb.record_failure()
        assert not await cb.is_open()
        await cb.record_failure()
        assert await cb.is_open()

    async def test_name_preserved(self):
        cb = CircuitBreaker("my-service")
        assert cb.name == "my-service"


class TestSafeCall:
    """Tests for composer._safe_call integration with CircuitBreaker."""

    @pytest.fixture(autouse=True)
    def reset_breakers(self):
        """Reset circuit breakers before each test."""
        from app.services.composer import _breakers

        for cb in _breakers.values():
            cb._failure_count = 0
            cb._open_until = 0.0

    async def test_safe_call_success(self):
        from app.services.composer import _safe_call

        warnings: list[Warning] = []
        result = await _safe_call("geocoder", self._async_value("ok"), warnings)
        assert result == "ok"
        assert len(warnings) == 0

    async def test_safe_call_exception_adds_warning(self):
        from app.services.composer import _safe_call

        warnings: list[Warning] = []
        coro = self._async_raise(RuntimeError("API down"))
        result = await _safe_call("geocoder", coro, warnings)
        assert result is None
        assert len(warnings) == 1
        assert warnings[0].module == "geocoder"
        assert "API down" in warnings[0].error

    async def test_safe_call_circuit_open_skips_call(self):
        from app.services.composer import _breakers, _safe_call

        # Force circuit open
        _breakers["describer"]._failure_count = 5
        _breakers["describer"]._open_until = time.time() + 100

        warnings: list[Warning] = []
        result = await _safe_call("describer", self._async_value("should not run"), warnings)
        assert result is None
        assert len(warnings) == 1
        assert "Circuit breaker open" in warnings[0].error

    async def test_safe_call_records_failure_on_exception(self):
        from app.services.composer import _breakers, _safe_call

        warnings: list[Warning] = []
        for _ in range(5):
            await _safe_call("landcover", self._async_raise(RuntimeError("fail")), warnings)

        assert await _breakers["landcover"].is_open()

    async def test_safe_call_records_success(self):
        from app.services.composer import _breakers, _safe_call

        # Add some failures first
        _breakers["context"]._failure_count = 3
        warnings: list[Warning] = []
        await _safe_call("context", self._async_value("ok"), warnings)
        assert _breakers["context"]._failure_count == 0

    @staticmethod
    async def _async_value(val):
        return val

    @staticmethod
    async def _async_raise(exc):
        raise exc


class TestExternalModuleErrorHandling:
    """Tests for error handling in external API modules.

    NOTE: After PR #52 (retry/circuit-breaker) is merged, geocoder/landcover/context
    will be decorated with @retry_http (up to 3 attempts for HTTP 500 and timeouts).
    Each test registers responses for all 3 attempts and patches asyncio.sleep to
    avoid ~3 seconds of backoff delay.
    """

    _RETRY_ATTEMPTS = 3  # stop_after_attempt(3) in retry_http

    @pytest.fixture
    async def cache(self, tmp_path):
        from app.cache.store import CacheStore

        store = CacheStore(str(tmp_path / "test.db"))
        await store.init()
        yield store
        await store.close()

    @pytest.fixture
    def no_retry_sleep(self, monkeypatch):
        """Patch asyncio.sleep to eliminate tenacity backoff delay in tests."""

        async def _instant_sleep(_):
            pass

        monkeypatch.setattr("asyncio.sleep", _instant_sleep)

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_geocoder_http_error(self, cache, httpx_mock, no_retry_sleep):
        for _ in range(self._RETRY_ATTEMPTS):
            httpx_mock.add_response(status_code=500)
        with pytest.raises(Exception):
            await __import__("app.modules.geocoder", fromlist=["geocode"]).geocode(
                126.978, 37.566, cache
            )

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_landcover_http_error(self, cache, httpx_mock, no_retry_sleep):
        for _ in range(self._RETRY_ATTEMPTS):
            httpx_mock.add_response(status_code=500)
        with pytest.raises(Exception):
            await __import__("app.modules.landcover", fromlist=["get_land_cover"]).get_land_cover(
                126.978, 37.566, cache
            )

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_context_http_error_graceful(self, cache, httpx_mock, no_retry_sleep):
        """Context module handles errors gracefully (try/except) after all retries."""
        for _ in range(self._RETRY_ATTEMPTS):
            httpx_mock.add_response(status_code=500)
        from app.modules.context import research_context

        result = await research_context("서울", "2025-06-15", cache)
        assert len(result.events) == 0

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_geocoder_timeout(self, cache, httpx_mock, no_retry_sleep):
        import httpx

        for _ in range(self._RETRY_ATTEMPTS):
            httpx_mock.add_exception(httpx.ReadTimeout("timeout"))
        with pytest.raises(httpx.ReadTimeout):
            from app.modules.geocoder import geocode

            await geocode(126.978, 37.566, cache)

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_landcover_timeout(self, cache, httpx_mock, no_retry_sleep):
        import httpx

        for _ in range(self._RETRY_ATTEMPTS):
            httpx_mock.add_exception(httpx.ReadTimeout("timeout"))
        with pytest.raises(httpx.ReadTimeout):
            from app.modules.landcover import get_land_cover

            await get_land_cover(126.978, 37.566, cache)
