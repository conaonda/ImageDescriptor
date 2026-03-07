import time

import structlog

from app.utils.metrics import circuit_breaker_state

logger = structlog.get_logger()


class CircuitBreaker:
    """Circuit breaker: 연속 failure_threshold회 실패 시 cooldown_sec초간 비활성화."""

    def __init__(self, name: str, failure_threshold: int = 5, cooldown_sec: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._failure_count = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        if self._open_until and time.time() < self._open_until:
            return True
        if self._open_until and time.time() >= self._open_until:
            # half-open: reset and allow retry
            self._open_until = 0.0
            self._failure_count = 0
            circuit_breaker_state.labels(name=self.name).set(2)
        return False

    def record_success(self):
        self._failure_count = 0
        self._open_until = 0.0
        circuit_breaker_state.labels(name=self.name).set(0)

    def get_status(self) -> dict:
        is_open = self.is_open
        cooldown_remaining = max(0.0, self._open_until - time.time()) if is_open else 0.0
        return {
            "name": self.name,
            "state": "open" if is_open else "closed",
            "failure_count": self._failure_count,
            "cooldown_remaining": round(cooldown_remaining, 1),
        }

    def record_failure(self):
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._open_until = time.time() + self.cooldown_sec
            circuit_breaker_state.labels(name=self.name).set(1)
            logger.warning(
                "circuit breaker opened",
                name=self.name,
                cooldown=self.cooldown_sec,
            )
