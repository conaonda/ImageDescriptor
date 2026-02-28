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
| POST | `/api/geocode` | 10/min | 좌표 → 주소 변환 |
| POST | `/api/landcover` | 10/min | 토지피복 분류 조회 |
| POST | `/api/context` | 10/min | 주변 맥락 정보 조회 |
| GET | `/api/descriptions/{cog_image_id}` | 30/min | 저장된 설명 조회 |

## 요청 형식

```json
{
  "thumbnail": "data:image/png;base64,... 또는 https://...",
  "coordinates": [경도, 위도],
  "captured_at": "2025-06-15T00:00:00Z",
  "cog_image_id": "선택사항 - DB 저장/캐시용"
}
```

## 에러 코드

| HTTP | code | 설명 |
|------|------|------|
| 400 | INVALID_COORDINATES | 좌표 범위 초과 |
| 401 | UNAUTHORIZED | 인증 실패 |
| 404 | NOT_FOUND | 설명 데이터 없음 |
| 422 | THUMBNAIL_TOO_LARGE | 썸네일 5MB 초과 |
| 429 | - | Rate limit 초과 |
| 500 | INTERNAL_ERROR | 서버 내부 오류 |

## Rate Limit

- POST 엔드포인트: 10 requests/minute (IP 기준)
- GET /descriptions: 30 requests/minute (IP 기준)
- 초과 시 `429 Too Many Requests` 응답
- Cloud Run 환경에서는 `X-Forwarded-For` 헤더의 첫 번째 IP를 사용
