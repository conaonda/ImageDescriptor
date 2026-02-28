import hmac
import time

import httpx
from fastapi import Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings
from app.utils.errors import DescriptorError

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

_jwks_cache: dict | None = None
_jwks_cache_ts: float = 0.0
_JWKS_TTL: float = 3600.0


async def _get_jwks() -> dict:
    """Fetch Supabase JWKS public keys (cached with TTL)."""
    global _jwks_cache, _jwks_cache_ts
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_cache_ts) < _JWKS_TTL:
        return _jwks_cache
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
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
        return {"type": "api_key"}

    # 2) Bearer JWT
    if credentials:
        try:
            jwks = await _get_jwks()
            payload = _verify_jwt(credentials.credentials, jwks)
            return {"type": "jwt", "sub": payload["sub"]}
        except JWTError:
            pass

    raise DescriptorError(
        status_code=401,
        code="UNAUTHORIZED",
        message="Valid API key or JWT required",
    )
