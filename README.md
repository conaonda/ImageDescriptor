# COGnito Image Descriptor

위성영상 좌표 기반 설명 생성 서비스. 좌표와 썸네일을 입력받아 위치 정보, 토지피복, 주변 맥락을 조합해 자연어 설명을 생성한다.

## 빠른 시작

```bash
cp .env.example .env
# .env 파일에 실제 키 값 입력

uv sync
uv run uvicorn app.main:app --reload
```

서버: `http://localhost:8000` | API 문서: `http://localhost:8000/docs`

## 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `GOOGLE_AI_API_KEY` | O | - | Gemini API 키 |
| `SUPABASE_URL` | O | - | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | O | - | Supabase 서비스 키 |
| `API_KEY` | O | - | 내부 API 인증 키 |
| `NOMINATIM_URL` | - | `https://nominatim.openstreetmap.org` | Nominatim 서버 |
| `OVERPASS_URL` | - | `https://overpass-api.de/api/interpreter` | Overpass API 서버 |
| `CORS_ORIGINS` | - | `http://localhost:5173,http://localhost:3000` | CORS 허용 오리진 (쉼표 구분) |
| `CACHE_DB_PATH` | - | `./cache.db` | 캐시 DB 경로 |
| `LOG_LEVEL` | - | `INFO` | 로그 레벨 |
| `THUMBNAIL_MAX_PIXELS` | - | `768` | Gemini 전송 전 이미지 리사이즈 최대 픽셀 |

## 인증

모든 API 요청(`/api/health` 제외)에 `X-API-Key` 헤더가 필요하다.

```
X-API-Key: your-api-key
```

## API 레퍼런스

### `GET /api/health`

헬스 체크. 인증 불필요.

```bash
curl http://localhost:8000/api/health
```

```json
{"status": "ok", "version": "0.2.0"}
```

### `POST /api/describe`

메인 엔드포인트. 좌표와 썸네일로 종합 설명을 생성한다.

```bash
curl -X POST http://localhost:8000/api/describe \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "thumbnail": "base64-encoded-png-or-url",
    "coordinates": [126.978, 37.566],
    "captured_at": "2025-01-15T00:00:00Z",
    "bbox": [126.97, 37.56, 126.99, 37.57],
    "cog_image_id": "optional-uuid"
  }'
```

**요청 필드:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `thumbnail` | string | O | base64 PNG 또는 이미지 URL |
| `coordinates` | [float, float] | O | [경도, 위도] |
| `captured_at` | string | O | 촬영일 (ISO 8601) |
| `bbox` | [float, float, float, float] | - | [west, south, east, north] |
| `cog_image_id` | string | - | DB 연동용 cog_images UUID |

**응답:**

```json
{
  "description": "서울특별시 중구에 위치한 도심 지역으로...",
  "location": {
    "country": "South Korea",
    "country_code": "KR",
    "region": "Seoul",
    "city": "Jung-gu",
    "place_name": "Seoul, Jung-gu",
    "lat": 37.566,
    "lon": 126.978
  },
  "land_cover": {
    "classes": [
      {"type": "building", "label": "건물", "percentage": 45.0}
    ],
    "summary": "도심 건물 밀집 지역"
  },
  "context": {
    "events": [
      {
        "title": "관련 이벤트",
        "date": "2025-01-10",
        "source_url": "https://example.com",
        "relevance": "medium"
      }
    ],
    "summary": "주변 맥락 요약"
  },
  "warnings": [],
  "cached": false
}
```

### `POST /api/geocode`

좌표를 주소로 변환한다.

```bash
curl -X POST http://localhost:8000/api/geocode \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"thumbnail": "", "coordinates": [126.978, 37.566], "captured_at": "2025-01-15"}'
```

**응답:** `Location` 객체

### `POST /api/landcover`

좌표 주변 토지피복 정보를 조회한다.

```bash
curl -X POST http://localhost:8000/api/landcover \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"thumbnail": "", "coordinates": [126.978, 37.566], "captured_at": "2025-01-15"}'
```

**응답:** `LandCover` 객체

### `POST /api/context`

좌표 주변 뉴스/이벤트 맥락을 조회한다.

```bash
curl -X POST http://localhost:8000/api/context \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"thumbnail": "", "coordinates": [126.978, 37.566], "captured_at": "2025-01-15"}'
```

**응답:** `Context` 객체

### `GET /api/descriptions/{cog_image_id}`

저장된 설명을 조회한다. 인증 불필요.

```bash
curl http://localhost:8000/api/descriptions/some-uuid
```

## 에러 코드

| 코드 | HTTP 상태 | 설명 |
|------|----------|------|
| `INVALID_API_KEY` | 401 | API 키가 유효하지 않음 |
| `INVALID_COORDINATES` | 400 | 좌표 범위 초과 (경도 -180~180, 위도 -90~90) |
| `THUMBNAIL_TOO_LARGE` | 422 | 썸네일 크기 초과 (최대 5MB) |
| `NOT_FOUND` | 404 | 해당 cog_image_id의 설명이 없음 |

에러 응답 형식:

```json
{"code": "INVALID_COORDINATES", "message": "Invalid coordinates range", "details": {"lon": 200, "lat": 37.5}}
```

## Rate Limiting

인증 필요 엔드포인트: **10 req/min per IP**

## 테스트

```bash
uv run pytest -v
```
