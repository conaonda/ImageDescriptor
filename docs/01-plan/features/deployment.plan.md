# Deployment Environment Plan

> **Feature**: ImageDescriptor 서비스 배포 환경 구축
>
> **Project**: COGnito Image Descriptor Service
> **Author**: conaonda
> **Date**: 2026-02-26
> **Status**: Draft

---

## 1. Background & Problem

현재 ImageDescriptor 서비스는 로컬 개발 환경에서만 실행 가능하며, 프로덕션 배포 환경이 없다.
COGnito 프론트엔드와 연동하려면 공개 접근 가능한 엔드포인트가 필요하다.

또한 main 브랜치에 직접 push가 차단되어 있으므로, PR 기반 워크플로우에 맞는 CI/CD 파이프라인이 필요하다.

---

## 2. Goals

| # | Goal | 측정 기준 |
|---|------|----------|
| 1 | 프로덕션 배포 환경 구축 | 공개 URL로 `/api/health` 응답 확인 |
| 2 | CI/CD 파이프라인 구성 | PR → 테스트 자동 실행, main merge → 자동 배포 |
| 3 | 환경변수 안전 관리 | 시크릿이 코드에 노출되지 않음 |
| 4 | 비용 최소화 | 월 $0~5 (저트래픽 기준) |

---

## 3. Scope

### In Scope
- **배포 플랫폼**: Fly.io (Docker 기반, 무료 티어 활용)
- **CI/CD**: GitHub Actions (PR 테스트 + 자동 배포)
- **환경변수**: Fly.io Secrets로 관리
- **헬스체크**: `/api/health` 엔드포인트 활용

### Out of Scope
- 커스텀 도메인 설정 (추후 필요 시)
- 모니터링/알림 시스템 (v1.3+)
- 멀티 리전 배포
- 로드 밸런서 / 오토스케일링 (Fly.io 기본 제공)

---

## 4. Platform Selection: Fly.io

### 선택 이유
| 기준 | Fly.io | Railway |
|------|--------|---------|
| Docker 지원 | 네이티브 | 네이티브 |
| 무료 티어 | 3 shared-cpu VMs, 256MB | $5 크레딧/월 |
| 리전 선택 | 전 세계 30+ | 제한적 |
| CLI 배포 | `fly deploy` | `railway up` |
| GitHub Actions 통합 | 공식 액션 제공 | 공식 액션 제공 |
| SQLite 지원 | Volume 마운트 가능 | 제한적 |

Fly.io는 SQLite 캐시 DB를 Volume으로 영속화할 수 있어 이 프로젝트에 적합하다.

---

## 5. Architecture

```
┌─────────────┐     PR/Push      ┌──────────────────┐
│  Developer   │ ──────────────▷ │  GitHub Actions   │
└─────────────┘                  │                    │
                                 │  1. ruff check     │
                                 │  2. pytest         │
                                 │  3. fly deploy     │
                                 └────────┬───────────┘
                                          │ (main merge only)
                                          ▼
                                 ┌──────────────────┐
                                 │    Fly.io         │
                                 │  ┌──────────────┐ │
                                 │  │  Docker       │ │
                                 │  │  Container    │ │
                                 │  │  (FastAPI)    │ │
                                 │  └──────┬───────┘ │
                                 │         │         │
                                 │  ┌──────▼───────┐ │
                                 │  │  Volume       │ │
                                 │  │  (cache.db)   │ │
                                 │  └──────────────┘ │
                                 └──────────────────┘
                                          │
                                          ▼
                                 ┌──────────────────┐
                                 │  Supabase DB      │
                                 └──────────────────┘
```

---

## 6. Implementation Items

### 6.1 Fly.io 설정 파일

| # | Item | 파일 | 설명 |
|---|------|------|------|
| 1 | `fly.toml` | 프로젝트 루트 | Fly.io 앱 설정 (리전, VM, 헬스체크, Volume) |
| 2 | Dockerfile 개선 | `Dockerfile` | 멀티스테이지 빌드, uv 활용, 비root 사용자 |

### 6.2 GitHub Actions 워크플로우

| # | Workflow | 트리거 | 단계 |
|---|----------|--------|------|
| 1 | `ci.yml` | PR open/sync | ruff check → pytest |
| 2 | `deploy.yml` | main push | ci → fly deploy |

### 6.3 환경변수 (Fly.io Secrets)

| Variable | 설정 방법 |
|----------|----------|
| `GOOGLE_AI_API_KEY` | `fly secrets set` |
| `SUPABASE_URL` | `fly secrets set` |
| `SUPABASE_SERVICE_KEY` | `fly secrets set` |
| `API_KEY` | `fly secrets set` |
| `CORS_ORIGINS` | `fly.toml` env (비밀 아님) |

---

## 7. Implementation Order

1. [ ] Dockerfile 개선 (멀티스테이지, 보안)
2. [ ] `fly.toml` 작성
3. [ ] GitHub Actions `ci.yml` (PR 테스트)
4. [ ] GitHub Actions `deploy.yml` (자동 배포)
5. [ ] Fly.io 앱 생성 + Secrets 설정 (수동)
6. [ ] 첫 배포 및 헬스체크 확인

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fly.io 무료 티어 제한 | 서비스 중단 | 사용량 모니터링, 필요 시 유료 전환 |
| SQLite Volume 손실 | 캐시 유실 | 캐시는 재생성 가능, 핵심 데이터는 Supabase |
| 시크릿 유출 | 보안 사고 | GitHub Secrets + Fly.io Secrets만 사용 |
| Gemini API 지연 | 응답 시간 증가 | 캐시 + 타임아웃 (이미 구현) |

---

## 9. Success Criteria

- [ ] `https://<app-name>.fly.dev/api/health` 200 OK 응답
- [ ] PR 생성 시 GitHub Actions CI 자동 실행
- [ ] main merge 시 자동 배포 완료
- [ ] 환경변수가 코드에 노출되지 않음

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-26 | Initial plan | conaonda |
