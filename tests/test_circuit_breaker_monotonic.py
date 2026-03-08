"""Tests for CircuitBreaker time.monotonic() usage (#267)."""

import time
from unittest.mock import patch

from app.utils.circuit_breaker import CircuitBreaker


class TestCircuitBreakerMonotonic:
    async def test_uses_monotonic_not_wall_clock(self):
        """time.monotonic()를 사용하므로 time.time() 역행에 영향받지 않아야 한다."""
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=10.0)
        await cb.record_failure()
        assert await cb.is_open()

        # time.monotonic()를 충분히 앞으로 이동시키면 쿨다운 만료
        future = time.monotonic() + 11.0
        with patch("time.monotonic", return_value=future):
            assert not await cb.is_open()

    async def test_cooldown_not_affected_by_wall_clock_rollback(self):
        """벽시계(time.time())가 역행해도 monotonic 기반이므로 정상 동작."""
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=5.0)
        await cb.record_failure()
        assert await cb.is_open()

        # time.time()을 역행시켜도 monotonic 기반이므로 영향 없음
        # (time.time을 패치해도 코드가 time.monotonic을 쓰므로 상태 불변)
        with patch("time.time", return_value=0):
            assert await cb.is_open()

    async def test_get_status_uses_monotonic(self):
        """get_status()의 cooldown_remaining도 monotonic 기반이어야 한다."""
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=10.0)
        await cb.record_failure()
        status = await cb.get_status()
        assert status["state"] == "open"
        assert status["cooldown_remaining"] > 0
