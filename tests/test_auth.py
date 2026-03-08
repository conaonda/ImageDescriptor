import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError

from app.auth import _JWKS_TTL, _get_jwks, authenticate
from app.utils.errors import DescriptorError

FAKE_JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "n": (
                "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAt"
                "VT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn6"
                "4tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_F"
                "DW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n"
                "91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksIN"
                "HaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw"
            ),
            "e": "AQAB",
            "alg": "RS256",
            "kid": "test-key-id",
            "use": "sig",
        }
    ]
}


@pytest.fixture(autouse=True)
def reset_jwks_cache():
    """Reset JWKS cache before each test."""
    import app.auth as auth_module

    auth_module._jwks_cache = None
    auth_module._jwks_cache_ts = 0.0
    yield
    auth_module._jwks_cache = None
    auth_module._jwks_cache_ts = 0.0


class TestApiKeyAuth:
    async def test_valid_api_key(self):
        with patch("app.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            result = await authenticate(api_key="correct-key", credentials=None)
            assert result == {"type": "api_key"}

    async def test_invalid_api_key_no_jwt(self):
        with patch("app.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            with pytest.raises(DescriptorError) as exc_info:
                await authenticate(api_key="wrong-key", credentials=None)
            assert exc_info.value.status_code == 401
            assert exc_info.value.code == "UNAUTHORIZED"

    async def test_timing_safe_comparison(self):
        """API key comparison uses hmac.compare_digest (timing-safe)."""
        with patch("app.auth.hmac.compare_digest", wraps=hmac.compare_digest) as mock_cmp:
            with patch("app.auth.settings") as mock_settings:
                mock_settings.api_key = "test-key"
                await authenticate(api_key="test-key", credentials=None)
                mock_cmp.assert_called_once_with("test-key", "test-key")


class TestJwtAuth:
    async def test_valid_jwt(self):
        fake_payload = {"sub": "user-123", "aud": "authenticated"}
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid.jwt.token")
        with (
            patch("app.auth._get_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
            patch("app.auth._verify_jwt", return_value=fake_payload),
            patch("app.auth.settings") as mock_settings,
        ):
            mock_settings.api_key = "different-key"
            result = await authenticate(api_key=None, credentials=creds)
            assert result == {"type": "jwt", "sub": "user-123"}

    async def test_expired_jwt(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="expired.jwt.token")
        with (
            patch("app.auth._get_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
            patch("app.auth._verify_jwt", side_effect=JWTError("expired")),
            patch("app.auth.settings") as mock_settings,
        ):
            mock_settings.api_key = "different-key"
            with pytest.raises(DescriptorError) as exc_info:
                await authenticate(api_key=None, credentials=creds)
            assert exc_info.value.status_code == 401

    async def test_invalid_signature_jwt(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.sig.token")
        with (
            patch("app.auth._get_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
            patch("app.auth._verify_jwt", side_effect=JWTError("bad signature")),
            patch("app.auth.settings") as mock_settings,
        ):
            mock_settings.api_key = "different-key"
            with pytest.raises(DescriptorError) as exc_info:
                await authenticate(api_key=None, credentials=creds)
            assert exc_info.value.status_code == 401

    async def test_wrong_audience_jwt(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong.aud.token")
        with (
            patch("app.auth._get_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
            patch("app.auth._verify_jwt", side_effect=JWTError("Invalid audience")),
            patch("app.auth.settings") as mock_settings,
        ):
            mock_settings.api_key = "different-key"
            with pytest.raises(DescriptorError) as exc_info:
                await authenticate(api_key=None, credentials=creds)
            assert exc_info.value.status_code == 401


class TestNoAuth:
    async def test_no_auth_header(self):
        with patch("app.auth.settings") as mock_settings:
            mock_settings.api_key = "some-key"
            with pytest.raises(DescriptorError) as exc_info:
                await authenticate(api_key=None, credentials=None)
            assert exc_info.value.status_code == 401
            assert exc_info.value.code == "UNAUTHORIZED"


class TestJwksCache:
    async def test_jwks_cache_hit(self):
        mock_response = MagicMock()
        mock_response.json.return_value = FAKE_JWKS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.http_client.get_client", return_value=mock_client):
            result1 = await _get_jwks()
            result2 = await _get_jwks()
            assert result1 == FAKE_JWKS
            assert result2 == FAKE_JWKS
            # Only one HTTP call due to cache
            assert mock_client.get.call_count == 1

    async def test_jwks_cache_expired(self):
        import app.auth as auth_module

        mock_response = MagicMock()
        mock_response.json.return_value = FAKE_JWKS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.http_client.get_client", return_value=mock_client):
            # First fetch
            await _get_jwks()
            # Expire the cache
            auth_module._jwks_cache_ts = time.monotonic() - _JWKS_TTL - 1
            # Second fetch should call HTTP again
            await _get_jwks()
            assert mock_client.get.call_count == 2
