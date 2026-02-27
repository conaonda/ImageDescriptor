import time

import structlog

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
        return False

    def record_success(self):
        self._failure_count = 0
        self._open_until = 0.0

    def record_failure(self):
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._open_until = time.time() + self.cooldown_sec
            logger.warning(
                "circuit breaker opened",
                name=self.name,
                cooldown=self.cooldown_sec,
            )
