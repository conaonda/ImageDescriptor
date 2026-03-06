# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- RFC 7807 Problem Details 에러 응답 표준화: `ProblemDetail` 모델(`type`, `title`, `status`, `detail`, `instance`) 도입. `ValidationError`(422), `HTTPException`, 내부 오류(500), 타임아웃(504) 모두 통일된 형식으로 반환
- 에러 응답 `Content-Type`: `application/problem+json` 적용
- 에러 응답 `instance` 필드에 `X-Correlation-ID` 자동 포함 → 요청 추적 연계
- OpenAPI 스키마 개선: `DescriptionItem` 스키마에 예제 데이터 추가, data 엔드포인트에 422 응답 문서화, 삭제 엔드포인트에 500 응답 문서화

## [0.22.0] - 2026-03-07

### Added

- 캐시 TTL 설정 외부화: `CACHE_TTL_SECONDS`, `CACHE_CLEANUP_INTERVAL_SECONDS` 환경변수로 캐시 만료 정책 설정 가능
- `X-Process-Time` 응답 헤더: API 요청 처리 시간을 초 단위(소수점 6자리)로 반환

## [0.21.0] - 2026-03-07

### Added

- `DELETE /api/descriptions/{cog_image_id}`: 저장된 분석 결과 삭제 API (204 성공, 404 미존재, 500 DB 오류)
- `GET /api/descriptions`: 설명 이력 목록 조회 API
- Correlation ID 지원: 모든 요청에 `X-Correlation-ID` 헤더를 통해 요청 추적 가능. 클라이언트가 헤더를 제공하면 UUID 검증 후 통과, 없으면 서버에서 자동 생성. 응답 헤더에 항상 포함됨.

## [0.18.0] - 2026-03-07

### Added

- API 요청/응답 로깅 미들웨어 개선: latency 측정(ms), 민감 정보 필터링, 시스템 경로 로그 스킵, 4xx/5xx warning 로깅
- 테스트 커버리지 97.61% 달성 (목표 95%): lifespan 테스트 6개, 데이터 엔드포인트 테스트 3개 추가

## [0.17.0] - 2026-03-06

### Added

- `GET /api/circuits`: Circuit breaker 상태 조회 엔드포인트 추가
- `HealthResponse`, `DependencyCheck`, `CacheStatsResponse`, `ModuleStats` Pydantic 응답 스키마 추가
- `/api/health`, `/api/cache/stats` 엔드포인트에 `response_model` 지정 (OpenAPI 문서 자동 반영)

### Changed

- structlog 로깅을 f-string에서 key-value 방식으로 전환

### Fixed

- CI lint 오류 수정 (ruff 규칙 위반)

## [0.16.0] - 2026-03-06

### Added

- Graceful shutdown: SIGTERM 시그널 핸들러, in-flight request draining, `/health`에 `shutting_down` 상태 반영
- Request timeout: `asyncio.wait_for` 기반 개별 요청 타임아웃 (기본 30초), 504 반환
- Batch concurrency: `asyncio.Semaphore` 기반 배치 동시성 제한 (기본 3)
- 신규 환경변수: `SHUTDOWN_TIMEOUT`, `REQUEST_TIMEOUT`, `BATCH_CONCURRENCY`

## [0.15.0] - 2026-03-06

### Added

- `X-Request-ID` 헤더 유효성 검증
- 캐시 응답 헤더 및 ETag 통합 테스트

## [0.14.0] - 2026-03-06

### Added

- API 응답 캐시 헤더 및 ETag 지원
- SSRF DNS rebinding 및 리다이렉트 보호 강화
- SQLite 캐시 만료 항목 자동 정리

## [0.3.1] - 2026-02-28

### Changed

- `captured_at` 필드를 optional로 변경 (촬영일자 없이도 설명 생성 가능)

## [0.3.0] - 2026-02-20

### Added

- API key 인증 및 Rate limiting
- Supabase 연동 (결과 저장)
- CORS 설정

## [0.2.0] - 2026-02-15

### Added

- Context 모듈 (DuckDuckGo 검색)
- LandCover 모듈 (Overpass API)
- Geocoder 모듈 (Nominatim)

## [0.1.0] - 2026-02-10

### Added

- Describer 모듈 (Gemini 2.0 Flash)
- 기본 FastAPI 구조
