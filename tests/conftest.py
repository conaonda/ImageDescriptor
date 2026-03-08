import os
from pathlib import Path

import pytest

# .env 파일이 있으면 로드 (실제 키 → E2E 테스트용)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# .env 없어도 mock 테스트가 돌도록 더미 값 설정
os.environ.setdefault("GOOGLE_AI_API_KEY", "test-dummy-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-dummy-key")
os.environ.setdefault("API_KEY", "test-key")

_has_real_keys = os.environ.get("GOOGLE_AI_API_KEY", "") != "test-dummy-key"


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end test requiring real API keys (.env)")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("-m", default=""):
        skip_e2e = pytest.mark.skip(reason="E2E 테스트: -m e2e 로 명시 실행 필요")
        for item in items:
            if "e2e" in item.keywords:
                if not _has_real_keys:
                    item.add_marker(pytest.mark.skip(reason=".env 파일에 실제 API 키가 필요합니다"))
                else:
                    item.add_marker(skip_e2e)


@pytest.fixture(autouse=True)
def _reset_supabase_backoff():
    """테스트 간 Supabase 재연결 백오프 상태를 리셋한다."""
    import app.db.supabase as _supa

    _supa._client = None
    _supa._last_failure_time = 0.0
    _supa._consecutive_failures = 0
    yield
    _supa._client = None
    _supa._last_failure_time = 0.0
    _supa._consecutive_failures = 0


@pytest.fixture
async def authenticated_client():
    from httpx import ASGITransport, AsyncClient

    from app.cache.store import CacheStore
    from app.config import settings
    from app.main import app

    # lifespan이 ASGI transport에서 실행되지 않으므로 수동 초기화
    cache = CacheStore(settings.cache_db_path)
    await cache.init()
    app.state.cache = cache

    api_key = os.environ["API_KEY"]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as c:
        yield c

    await cache.close()
