from starlette.requests import Request


def get_real_ip(request: Request) -> str:
    """Extract real client IP from X-Forwarded-For header (Cloud Run sets this)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"
