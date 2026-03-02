"""E2E 통합 테스트 — 실제 외부 API 호출.

실행: uv run pytest -m e2e -v -s
필수: .env 파일에 실제 API 키 설정
"""

import json

import pytest


@pytest.mark.e2e
async def test_describe_full(authenticated_client):
    """실제 Supabase 썸네일 URL로 /api/describe E2E 테스트."""
    resp = await authenticated_client.post(
        "/api/describe",
        json={
            "thumbnail": (
                "https://nfbvxuwimdjgnegkvzwo.supabase.co/storage/v1/object/public"
                "/cog-thumbnails/f1fabf89-c07d-4bd6-9e3d-883187b24512.png"
            ),
            "coordinates": [127.35975356339686, 37.44137290680084],
            "captured_at": "2026-02-25T00:00:00.000Z",
            "bbox": [
                126.75422786915422,
                36.93664192316741,
                127.97343994103075,
                37.94311117380608,
            ],
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

    # 전체 응답 출력
    print("\n=== /api/describe 응답 ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))


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
