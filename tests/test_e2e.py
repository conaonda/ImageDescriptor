"""E2E 통합 테스트 — 실제 외부 API 호출.

실행: uv run pytest -m e2e -v
필수: .env 파일에 실제 API 키 설정
"""

import base64
import io

import pytest
from PIL import Image


def _make_test_thumbnail() -> str:
    """테스트용 작은 RGB 이미지를 base64 data URL로 생성."""
    img = Image.new("RGB", (64, 64), color=(100, 150, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


@pytest.mark.e2e
async def test_describe_full(authenticated_client):
    """기존 curl 테스트를 pytest로 재현."""
    resp = await authenticated_client.post(
        "/api/describe",
        json={
            "thumbnail": _make_test_thumbnail(),
            "coordinates": [127.20458984375, 37.40507375344987],
            "captured_at": "2026-02-25T05:12:07Z",
            "bbox": [
                126.56249999999999,
                36.80928470205937,
                127.84667968750001,
                37.99616267972814,
            ],
            "cog_image_id": None,
        },
        timeout=60.0,
    )
    assert resp.status_code == 200
    data = resp.json()

    # description
    assert data["description"], "description이 비어있음"
    assert len(data["description"]) > 50, f"description이 너무 짧음: {len(data['description'])}자"

    # location
    loc = data["location"]
    assert loc is not None, "location이 None"
    assert loc["region"], f"region이 비어있음: {loc}"
    assert loc["country"] == "대한민국"

    # land_cover
    lc = data["land_cover"]
    assert lc is not None, "land_cover가 None"
    assert len(lc["classes"]) > 0, "land_cover classes가 비어있음"

    # context
    ctx = data["context"]
    assert ctx is not None, "context가 None"

    # warnings
    assert len(data["warnings"]) == 0, f"warnings 발생: {data['warnings']}"


@pytest.mark.e2e
async def test_geocode_endpoint(authenticated_client):
    resp = await authenticated_client.post(
        "/api/geocode",
        json={
            "thumbnail": "",
            "coordinates": [126.978, 37.566],
        },
        timeout=15.0,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["country"] == "대한민국"
    assert data["region"], "region이 비어있음"


@pytest.mark.e2e
async def test_landcover_endpoint(authenticated_client):
    resp = await authenticated_client.post(
        "/api/landcover",
        json={
            "thumbnail": "",
            "coordinates": [126.978, 37.566],
        },
        timeout=20.0,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["classes"]) > 0, "land_cover classes가 비어있음"
