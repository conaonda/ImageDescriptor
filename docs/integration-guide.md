# COGnito ImageDescriptor 통합 가이드

## 인증 방식

ImageDescriptor API는 두 가지 인증 방식을 지원합니다.

### 1. Supabase JWT (프론트엔드용)

Supabase 세션에서 JWT 토큰을 가져와 `Authorization` 헤더로 전달합니다.

```typescript
const { data: { session } } = await supabase.auth.getSession();

const response = await fetch('https://cognito-descriptor-gdno3pyjba-an.a.run.app/api/describe', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${session.access_token}`,
  },
  body: JSON.stringify({
    thumbnail: '<base64 or URL>',
    coordinates: [126.978, 37.566],
    captured_at: '2025-06-15T00:00:00Z',
    cog_image_id: 'optional-id',
  }),
});
```

#### 토큰 갱신

Supabase SDK가 자동으로 토큰을 갱신합니다. `onAuthStateChange`로 세션 변경을 감지하세요:

```typescript
supabase.auth.onAuthStateChange((event, session) => {
  if (event === 'TOKEN_REFRESHED' && session) {
    // 새 access_token 사용
  }
});
```

### 2. API Key (서버간 통신 전용)

`X-API-Key` 헤더로 서버에 설정된 API 키를 전달합니다.

```bash
curl -X POST https://cognito-descriptor-gdno3pyjba-an.a.run.app/api/describe \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"thumbnail":"...","coordinates":[126.978,37.566],"captured_at":"2025-06-15T00:00:00Z"}'
```

## API 엔드포인트

| Method | Path | Rate Limit | 설명 |
|--------|------|------------|------|
| GET | `/api/health` | - | 헬스체크 (인증 불필요) |
| POST | `/api/describe` | 10/min | 위성영상 종합 설명 생성 |
| POST | `/api/describe/batch` | 별도 설정 | 배치 설명 생성 (최대 10건) |
| POST | `/api/geocode` | 10/min | 좌표 → 주소 변환 |
| POST | `/api/landcover` | 10/min | 토지피복 분류 조회 |
| POST | `/api/context` | 10/min | 주변 맥락 정보 조회 |
| GET | `/api/descriptions` | 30/min | 설명 이력 목록 조회 |
| GET | `/api/descriptions/{cog_image_id}` | 30/min | 저장된 설명 조회 |
| DELETE | `/api/descriptions/{cog_image_id}` | 30/min | 저장된 설명 삭제 |

## 요청 형식

```json
{
  "thumbnail": "data:image/png;base64,... 또는 https://...",
  "coordinates": [경도, 위도],
  "captured_at": "2025-06-15T00:00:00Z",
  "cog_image_id": "선택사항 - DB 저장/캐시용"
}
```

## 배치 API

### 요청

```json
POST /api/describe/batch
{
  "items": [
    {
      "thumbnail": "https://example.com/image1.jpg",
      "coordinates": [126.978, 37.566],
      "bbox": [126.9, 37.5, 127.1, 37.6],
      "captured_at": "2025-01-15"
    },
    {
      "thumbnail": "https://example.com/image2.jpg",
      "coordinates": [129.075, 35.179]
    }
  ]
}
```

- `items`: 배치 항목 목록 (1~10건 필수)
- 각 항목의 `coordinates`, `bbox`는 `/describe` 단건과 동일한 범위 검증 적용
  - `coordinates`: `[경도(-180~180), 위도(-90~90)]`
  - `bbox`: `[west, south, east, north]` — west < east, south < north 조건 필수
- 잘못된 좌표/bbox는 요청 단계에서 `422`로 즉시 거부

### 응답

```json
{
  "results": [
    {
      "index": 0,
      "result": { "description": "...", "cached": false, "warnings": [] },
      "error": null,
      "error_detail": null
    },
    {
      "index": 1,
      "result": null,
      "error": "Timeout exceeded",
      "error_detail": {
        "error_type": "timeout",
        "message": "Timeout exceeded",
        "details": null
      }
    }
  ],
  "total": 2,
  "succeeded": 1,
  "failed": 1,
  "interrupted": 0
}
```

#### `error_detail` 필드 (Sprint 52 추가)

`BatchItemResult`의 `error_detail` 필드는 에러 유형을 구분합니다:

| `error_type` | 설명 |
|---|---|
| `validation` | 좌표/bbox 범위 등 입력값 검증 실패 |
| `service` | 외부 API 호출 실패 등 서비스 오류 |
| `timeout` | 개별 항목 처리 타임아웃 |

기존 `error` 문자열 필드는 하위 호환성을 위해 유지됩니다.

## 에러 응답 형식

모든 에러 응답은 [RFC 7807 Problem Details](https://datatracker.ietf.org/doc/html/rfc7807) 표준을 따르며 `Content-Type: application/problem+json`으로 반환됩니다.

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "Description not found for image: abc-123",
  "instance": "urn:request:550e8400-e29b-41d4-a716-446655440000"
}
```

- `type`: 에러 유형 URI
- `title`: HTTP 상태에 대응하는 짧은 제목
- `status`: HTTP 상태 코드
- `detail`: 사람이 읽기 쉬운 에러 설명
- `instance`: 요청 식별자 (`X-Correlation-ID` 연계)

`422 Validation Error`의 경우 `errors` 필드가 추가로 포함됩니다:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "Request validation failed",
  "instance": "urn:request:...",
  "errors": [{"loc": ["body", "coordinates"], "msg": "field required", "type": "missing"}]
}
```

## 에러 코드

| HTTP | 설명 |
|------|------|
| 400 | 좌표 범위 초과 등 잘못된 요청 |
| 401 | 인증 실패 |
| 404 | 설명 데이터 없음 |
| 422 | 요청 유효성 검증 실패 (body 형식 오류 등) |
| 429 | Rate limit 초과 |
| 500 | 서버 내부 오류 |
| 504 | 요청 처리 타임아웃 |

## Rate Limit

- POST 엔드포인트: 10 requests/minute (IP 기준)
- GET /descriptions, DELETE /descriptions/{id}: 30 requests/minute (IP 기준)
- 초과 시 `429 Too Many Requests` 응답
- Cloud Run 환경에서는 `X-Forwarded-For` 헤더의 첫 번째 IP를 사용
