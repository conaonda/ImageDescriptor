import logging
import re
import uuid

import structlog
from starlette.requests import Request

from app.config import settings

_VALID_REQUEST_ID = re.compile(r"^[\w\-]{1,128}$")


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


def _sanitize_request_id(value: str | None) -> str | None:
    """Validate and sanitize a client-provided request ID."""
    if value and _VALID_REQUEST_ID.match(value):
        return value
    return None


async def request_id_middleware(request: Request, call_next):
    """Middleware that binds a unique request_id to each request's log context."""
    request_id = _sanitize_request_id(request.headers.get("x-request-id")) or generate_request_id()
    request.state.request_id = request_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    logger = structlog.get_logger()
    await logger.ainfo(
        "request_started",
        method=request.method,
        path=request.url.path,
    )

    response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    await logger.ainfo(
        "request_finished",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
    )

    structlog.contextvars.clear_contextvars()
    return response
