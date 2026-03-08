"""Tests for CircuitBreaker asyncio.Lock (concurrent state consistency)."""

import asyncio

from app.utils.circuit_breaker import CircuitBreaker


class TestCircuitBreakerConcurrency:
    async def test_concurrent_failures_consistent_count(self):
        """Concurrent record_failure calls should produce consistent failure count."""
        cb = CircuitBreaker("test", failure_threshold=100, cooldown_sec=30.0)
        await asyncio.gather(*[cb.record_failure() for _ in range(50)])
        assert cb._failure_count == 50

    async def test_concurrent_success_resets(self):
        """Concurrent record_success calls should all reset cleanly."""
        cb = CircuitBreaker("test", failure_threshold=100, cooldown_sec=30.0)
        # Add some failures first
        for _ in range(10):
            await cb.record_failure()
        await asyncio.gather(*[cb.record_success() for _ in range(10)])
        assert cb._failure_count == 0
        assert not await cb.is_open()

    async def test_concurrent_mixed_operations(self):
        """Mixed concurrent success/failure should not corrupt state."""
        cb = CircuitBreaker("test", failure_threshold=100, cooldown_sec=30.0)
        tasks = [cb.record_failure() for _ in range(20)] + [cb.record_success() for _ in range(5)]
        await asyncio.gather(*tasks)
        # State should be internally consistent (no exceptions, valid count)
        assert cb._failure_count >= 0
