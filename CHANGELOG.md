# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
