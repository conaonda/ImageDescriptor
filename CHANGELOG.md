# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- geocoder, landcover, mission 모듈에서 `resp.json()` 호출 시 `JSONDecodeError` 예외를 catch하여 graceful fallback 처리 (#239): geocoder는 Unknown Location 반환, landcover는 빈 결과 반환, mission은 None 반환
- mission 모듈의 STAC API 요청 타임아웃을 `settings.timeout_mission`으로 외부화 (#240): `TIMEOUT_MISSION` 환경변수로 설정 가능 (기본값: 10.0초)
- describer의 이미지 다운로드 제한값을 Settings로 외부화 (#241): `MAX_IMAGE_DOWNLOAD_BYTES`(기본 5MB), `MAX_IMAGE_REDIRECTS`(기본 5)로 환경변수 설정 가능

### Added

- API 버전 관리 도입: 모든 엔드포인트가 `/api/v1/` prefix를 사용. 레거시 `/api/*` 경로는 `/api/v1/*`으로 307 영구 리다이렉트하여 하위 호환성 유지
- 엔드포인트별 Rate Limiting 세분화: describe(20/min), batch(10/min), data(30/min), read(60/min). 환경변수(`RATE_LIMIT_DESCRIBE`, `RATE_LIMIT_BATCH`, `RATE_LIMIT_DATA`, `RATE_LIMIT_READ`)로 외부 설정 가능
- Rate Limit 초과 시 RFC 7807 형식 에러 응답 + RFC 7231 준수 `Retry-After` 헤더(초 단위 정수) 반환
- GZip 응답 압축 미들웨어 추가: `Accept-Encoding: gzip` 요청 시 응답 자동 압축. `GZIP_MIN_SIZE` 환경변수로 최소 압축 크기 설정 가능 (기본값: 500 bytes)
- K8s probe 엔드포인트 분리 (#188): `GET /api/v1/health/ready` (Readiness — DB·캐시 의존성 포함), `GET /api/v1/health/live` (Liveness — 프로세스 생존만 확인, 경량). 기존 `GET /api/v1/health`는 하위 호환성 유지
- Prometheus 커스텀 메트릭 강화 (#187): `description_requests_total` Counter(성공/실패 추적), `active_batch_jobs` Gauge(진행 중 배치 수), `circuit_breaker_state` Gauge(0=closed, 1=open, 2=half-open 3단계) 추가
- 설정값 시작 시 유효성 검증 (#186): `field_validator`로 양수 값·rate_limit 패턴·CORS origin URL 형식 검증. 잘못된 설정은 명확한 에러 메시지와 함께 시작 실패. 시작 시 API 키 마스킹된 설정 요약 로그 출력
- OpenTelemetry trace context 전파 및 구조화 로깅 강화 (#189): W3C `traceparent` 헤더 파싱으로 `trace_id`·`span_id`를 structlog 컨텍스트에 바인딩. 응답 로그에 `response_size`, `client_ip` 필드 추가. structlog 프로세서로 `service_name`, `environment` 필드 자동 삽입. 기존 `X-Correlation-ID`와 완전 공존
- pytest 커버리지 CI 연동 (#194): `--cov-fail-under=80` 임계값 설정, `coverage.json` 아티팩트 업로드. 현재 커버리지 98%로 임계값 충족
- README 커버리지 뱃지 동적 갱신 (#197): 정적 하드코딩 뱃지(`98%`)를 Codecov 동적 뱃지로 교체. CI 워크플로우에 `codecov/codecov-action@v5` 업로드 스텝 추가(Python 3.11 매트릭스). 커버리지 변동 시 README 뱃지 자동 갱신
- 의존성 보안 취약점 자동 스캔 CI 파이프라인 추가 (#200): `pip-audit`을 dev 의존성에 추가하고 GitHub Actions에 `security-audit` 잡 신설. 취약점 발견 시 빌드 실패. 감사 결과를 JSON 아티팩트로 업로드
- Docker 이미지 경량화 (#193): Runtime 이미지를 `python:3.11-slim` → `python:3.11-alpine`으로 교체하여 이미지 크기 약 50% 감소. Build stage에서 `__pycache__`/`.pyc`/`.pyo` 제거, `PYTHONDONTWRITEBYTECODE=1` 설정. `.dockerignore`에 `coverage.xml`, `dist/`, `build/`, `htmlcov/` 추가
- 배치 Graceful Shutdown 구현 (#203): SIGTERM 수신 시 진행 중인 배치 항목을 `interrupted: server shutting down`으로 안전하게 마킹 후 종료. lifespan에서 `active_batch_jobs` 게이지가 0이 될 때까지 대기 후 드레인 수행. `SHUTDOWN_BATCH_TIMEOUT` 환경변수 추가 (기본 60초, K8s `terminationGracePeriodSeconds` 연계)

### Fixed

- docker-compose.yml healthcheck 경로를 `/api/health` → `/api/v1/health`로 수정하여 Dockerfile과 정합성 일치
- Dockerfile 및 docker-compose HEALTHCHECK 대상을 `/api/v1/health` → `/api/v1/health/live`로 변경 (Liveness probe 전용 경량 엔드포인트 사용)

### Security

- OWASP 기반 보안 네거티브 테스트 28건 추가: 비정상 좌표값, 과도한 입력, 잘못된 Content-Type, 인증 우회 시도, 보안 헤더 검증 포함

## [0.24.0] - 2026-03-07

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
