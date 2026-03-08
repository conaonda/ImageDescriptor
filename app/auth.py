import hmac
import json
import time

import structlog
from fastapi import Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings
from app.utils.errors import DescriptorError

logger = structlog.get_logger()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

_jwks_cache: dict | None = None
_jwks_cache_ts: float = 0.0


async def _get_jwks() -> dict:
    """Fetch Supabase JWKS public keys (cached with TTL)."""
    global _jwks_cache, _jwks_cache_ts
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_cache_ts) < settings.jwks_ttl_seconds:
        return _jwks_cache
    from app.http_client import get_client

    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    client = await get_client()
    resp = await client.get(url)
    resp.raise_for_status()
    try:
        data = resp.json()
    except json.JSONDecodeError:
        logger.warning("jwks_invalid_json", url=url, body=resp.text[:200])
        raise DescriptorError(
            status_code=502,
            code="JWKS_PARSE_ERROR",
            message="Failed to parse JWKS response from auth provider",
        )
    _jwks_cache = data
    _jwks_cache_ts = now
    return _jwks_cache


def _verify_jwt(token: str, jwks: dict) -> dict:
    """Verify Supabase JWT signature and return payload."""
    return jwt.decode(token, jwks, algorithms=["RS256"], audience="authenticated")


async def authenticate(
    api_key: str | None = Security(api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> dict:
    """Authenticate via API Key or JWT. Returns auth info dict or raises 401."""
    # 1) API Key (timing-safe comparison)
    if api_key and hmac.compare_digest(api_key, settings.api_key):
        logger.debug("auth_success", auth_type="api_key")
        return {"type": "api_key"}

    # 2) Bearer JWT
    if credentials:
        try:
            jwks = await _get_jwks()
            payload = _verify_jwt(credentials.credentials, jwks)
            logger.debug("auth_success", auth_type="jwt", sub=payload["sub"])
            return {"type": "jwt", "sub": payload["sub"]}
        except JWTError:
            logger.warning("auth_jwt_invalid")

    logger.warning("auth_failed")
    raise DescriptorError(
        status_code=401,
        code="UNAUTHORIZED",
        message="Valid API key or JWT required",
    )
