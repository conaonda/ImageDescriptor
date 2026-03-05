"""PR #53 OpenAPI/Swagger 문서 메타데이터 검증 테스트."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture
def openapi_schema():
    return app.openapi()


# ── 앱 메타데이터 ──────────────────────────────────────────────────────────────

def test_app_title(openapi_schema):
    assert openapi_schema["info"]["title"] == "COGnito Image Descriptor"


def test_app_version(openapi_schema):
    assert openapi_schema["info"]["version"] == "0.6.0"


def test_app_description(openapi_schema):
    assert "위성영상 분석 API" in openapi_schema["info"]["description"]


# ── 태그 정의 ──────────────────────────────────────────────────────────────────

def test_openapi_tags_defined(openapi_schema):
    tag_names = {t["name"] for t in openapi_schema.get("tags", [])}
    assert {"analysis", "data", "system"} == tag_names


def test_openapi_tag_analysis_description(openapi_schema):
    tags = {t["name"]: t for t in openapi_schema.get("tags", [])}
    assert "위성영상" in tags["analysis"]["description"]


def test_openapi_tag_data_description(openapi_schema):
    tags = {t["name"]: t for t in openapi_schema.get("tags", [])}
    assert tags["data"]["description"]


def test_openapi_tag_system_description(openapi_schema):
    tags = {t["name"]: t for t in openapi_schema.get("tags", [])}
    assert tags["system"]["description"]


# ── 엔드포인트 태그 ────────────────────────────────────────────────────────────

def _get_op(openapi_schema, method: str, path: str) -> dict:
    return openapi_schema["paths"][path][method]


def test_health_tag(openapi_schema):
    op = _get_op(openapi_schema, "get", "/api/health")
    assert "system" in op["tags"]


def test_cache_stats_tag(openapi_schema):
    op = _get_op(openapi_schema, "get", "/api/cache/stats")
    assert "system" in op["tags"]


def test_describe_tag(openapi_schema):
    op = _get_op(openapi_schema, "post", "/api/describe")
    assert "analysis" in op["tags"]


def test_geocode_tag(openapi_schema):
    op = _get_op(openapi_schema, "post", "/api/geocode")
    assert "data" in op["tags"]


def test_landcover_tag(openapi_schema):
    op = _get_op(openapi_schema, "post", "/api/landcover")
    assert "data" in op["tags"]


def test_context_tag(openapi_schema):
    op = _get_op(openapi_schema, "post", "/api/context")
    assert "data" in op["tags"]


def test_descriptions_tag(openapi_schema):
    op = _get_op(openapi_schema, "get", "/api/descriptions/{cog_image_id}")
    assert "analysis" in op["tags"]


# ── 엔드포인트 summary / description ──────────────────────────────────────────

def test_health_summary(openapi_schema):
    assert _get_op(openapi_schema, "get", "/api/health")["summary"]


def test_describe_summary(openapi_schema):
    assert _get_op(openapi_schema, "post", "/api/describe")["summary"]


def test_describe_description(openapi_schema):
    op = _get_op(openapi_schema, "post", "/api/describe")
    assert "Gemini" in op.get("description", "")


def test_geocode_summary(openapi_schema):
    assert _get_op(openapi_schema, "post", "/api/geocode")["summary"]


def test_landcover_summary(openapi_schema):
    assert _get_op(openapi_schema, "post", "/api/landcover")["summary"]


def test_context_summary(openapi_schema):
    assert _get_op(openapi_schema, "post", "/api/context")["summary"]


# ── 오류 응답 문서화 ───────────────────────────────────────────────────────────

def test_describe_has_422_response(openapi_schema):
    responses = _get_op(openapi_schema, "post", "/api/describe")["responses"]
    assert "422" in responses


def test_describe_has_429_response(openapi_schema):
    responses = _get_op(openapi_schema, "post", "/api/describe")["responses"]
    assert "429" in responses


def test_descriptions_has_404_response(openapi_schema):
    responses = _get_op(openapi_schema, "get", "/api/descriptions/{cog_image_id}")["responses"]
    assert "404" in responses


def test_geocode_has_429_response(openapi_schema):
    responses = _get_op(openapi_schema, "post", "/api/geocode")["responses"]
    assert "429" in responses


# ── DescribeRequest 스키마 예시 ────────────────────────────────────────────────

def test_describe_request_schema_has_examples(openapi_schema):
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    assert "DescribeRequest" in schemas
    req = schemas["DescribeRequest"]
    examples = req.get("examples") or req.get("example")
    assert examples, "DescribeRequest 스키마에 예시 데이터가 없습니다"


# ── OpenAPI JSON 엔드포인트 접근 가능 여부 ────────────────────────────────────

@pytest.mark.asyncio
async def test_openapi_json_endpoint(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["info"]["title"] == "COGnito Image Descriptor"


@pytest.mark.asyncio
async def test_docs_endpoint(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
