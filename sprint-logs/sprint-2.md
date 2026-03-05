# Sprint 2 계획

**기간**: 2026-03-05 ~
**브랜치**: release/v0.4.0

## 선택된 이슈 (3개)

| # | 제목 | 라벨 | 우선순위 |
|---|------|------|----------|
| [#27](https://github.com/conaonda/ImageDescriptor/issues/27) | feat: 위성 미션 메타데이터 제공 (STAC 연동) | `agent/researcher` | 높음 |
| [#33](https://github.com/conaonda/ImageDescriptor/issues/33) | fix: bbox 필드 좌표 범위 검증 추가 | `agent/developer` | 중간 |
| [#34](https://github.com/conaonda/ImageDescriptor/issues/34) | feat: /health 엔드포인트 추가 | `agent/developer` | 중간 |

## 우선순위 판단 근거

1. **#27 (높음)**: 핵심 기능 확장. STAC 메타데이터를 통해 설명 품질이 크게 향상됨. 단, API 조사가 선행 필요하므로 `agent/researcher` 지정.
2. **#33 (중간)**: 데이터 무결성 이슈. bbox에 잘못된 값이 들어올 수 있는 취약점. 소규모 변경으로 빠르게 해결 가능.
3. **#34 (중간)**: 운영 안정성. 배포 환경에서 health check가 없으면 모니터링 불가. 소규모 변경.

## 작업 순서

1. #33, #34 — 독립적이므로 병렬 진행 가능 (developer)
2. #27 — 조사 완료 후 구현 (researcher → developer)

## 결과

**완료일**: 2026-03-05
**릴리스**: [v0.4.0](https://github.com/conaonda/ImageDescriptor/releases/tag/v0.4.0)

### 완료된 이슈

| # | PR | 상태 |
|---|-----|------|
| #33 | [PR #35](https://github.com/conaonda/ImageDescriptor/pull/35) | Merged |
| #34 | [PR #36](https://github.com/conaonda/ImageDescriptor/pull/36) | Merged |

### 미완료

| # | 사유 |
|---|------|
| #27 | researcher 단계에서 조사 완료. 구현은 Sprint 3으로 이월 |

### 테스트 결과

- PR #35: 16/16 통과
- PR #36: 11/11 통과
