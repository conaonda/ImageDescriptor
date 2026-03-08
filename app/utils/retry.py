"""Tenacity-based retry configurations per external service."""

import httpx
import structlog
from google.genai.errors import ClientError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger()


def _log_retry(retry_state: RetryCallState) -> None:
    """Log each retry attempt."""
    logger.warning(
        "retrying external call",
        attempt=retry_state.attempt_number,
        wait=round(retry_state.upcoming_sleep, 2) if hasattr(retry_state, "upcoming_sleep") else 0,
        error=str(retry_state.outcome.exception()) if retry_state.outcome else None,
    )


# Retryable exceptions: transient HTTP errors and connection issues
_TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient connection errors or retryable HTTP status codes."""
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return False


# Nominatim/Overpass/DuckDuckGo: 3 attempts, 1-4s exponential backoff
retry_http = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    before_sleep=_log_retry,
    reraise=True,
)


def _is_retryable_gemini(exc: BaseException) -> bool:
    """Return True for transient Gemini errors. ClientError (4xx) is not retryable."""
    if isinstance(exc, ClientError):
        return False
    return True


# Gemini API: 3 attempts, 2-8s exponential backoff (slower service, longer waits)
retry_gemini = retry(
    retry=retry_if_exception(_is_retryable_gemini),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    before_sleep=_log_retry,
    reraise=True,
)
