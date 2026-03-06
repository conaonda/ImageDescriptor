import logging
import re
import time
import uuid

import structlog
from starlette.requests import Request

from app.config import settings

_VALID_REQUEST_ID = re.compile(r"^[\w\-]{1,128}$")

_SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "x-api-key",
        "cookie",
        "set-cookie",
    }
)

_SKIP_LOG_PATHS = frozenset(
    {
        "/health",
        "/metrics",
        "/api/health",
        "/api/cache/stats",
    }
)


def setup_logging() -> None:
    """Configure structlog with JSON output and standard library integration."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def generate_request_id() -> str:
    return uuid.uuid4().hex[:16]


def generate_correlation_id() -> str:
    return str(uuid.uuid4())


def _sanitize_request_id(value: str | None) -> str | None:
    """Validate and sanitize a client-provided request ID."""
    if value and _VALID_REQUEST_ID.match(value):
        return value
    return None


def _safe_headers(headers) -> dict[str, str]:
    """Return headers with sensitive values redacted."""
    return {k: "[REDACTED]" if k.lower() in _SENSITIVE_HEADERS else v for k, v in headers.items()}


def _safe_query_params(query_string: str) -> str:
    """Return query string with api_key values redacted."""
    if not query_string:
        return ""
    return re.sub(
        r"(api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password)=([^&]*)",
        r"\1=[REDACTED]",
        query_string,
        flags=re.IGNORECASE,
    )


def _sanitize_correlation_id(value: str | None) -> str | None:
    """Validate a client-provided correlation ID (UUID format)."""
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None


async def request_id_middleware(request: Request, call_next):
    """Middleware that binds a unique request_id and correlation_id to each request's log context."""
    request_id = _sanitize_request_id(request.headers.get("x-request-id")) or generate_request_id()
    correlation_id = (
        _sanitize_correlation_id(request.headers.get("x-correlation-id"))
        or generate_correlation_id()
    )
    request.state.request_id = request_id
    request.state.correlation_id = correlation_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, correlation_id=correlation_id)

    path = request.url.path
    skip_log = path in _SKIP_LOG_PATHS

    logger = structlog.get_logger()
    start_time = time.monotonic()

    if not skip_log:
        await logger.ainfo(
            "request_started",
            method=request.method,
            path=path,
            query=_safe_query_params(str(request.query_params)),
            headers=_safe_headers(dict(request.headers)),
        )

    response = await call_next(request)

    latency_ms = round((time.monotonic() - start_time) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = correlation_id

    if not skip_log:
        log_method = logger.awarning if response.status_code >= 400 else logger.ainfo
        await log_method(
            "request_finished",
            method=request.method,
            path=path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
    elif response.status_code >= 400:
        await logger.awarning(
            "request_finished",
            method=request.method,
            path=path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

    structlog.contextvars.clear_contextvars()
    return response
