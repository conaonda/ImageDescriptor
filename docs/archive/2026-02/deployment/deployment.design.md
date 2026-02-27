# Deployment Environment Design Document

> **Summary**: Google Cloud Run + GitHub Actions 기반 ImageDescriptor 서비스 배포 환경 설계
>
> **Project**: COGnito Image Descriptor Service
> **Version**: 0.2.0
> **Author**: conaonda
> **Date**: 2026-02-27
> **Status**: Draft
> **Planning Doc**: [deployment.plan.md](../../01-plan/features/deployment.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- Docker 컨테이너 기반 Cloud Run 프로덕션 배포 (무료 티어 내)
- PR 테스트 자동화 + main merge 시 자동 배포
- 환경변수 안전 관리 (GCP Secret Manager)

### 1.2 Design Principles

- **비용 $0**: Cloud Run Always Free 한도 내 운영
- **최소 구성**: Dockerfile + 1 CI + 1 Deploy workflow
- **보안 우선**: 시크릿은 GitHub Secrets에서만 관리

### 1.3 Cloud Run 선택 이유

- Always Free: 200만 req/월, CPU 50시간, 메모리 100시간
- 저트래픽 ImageDescriptor는 무료 한도 내 운영 가능
- SQLite 캐시는 휘발되지만, 핵심 데이터는 Supabase에 저장됨

---

## 2. Dockerfile

```dockerfile
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --target=/deps .

FROM python:3.11-slim

RUN groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app
COPY --from=builder /deps /usr/local/lib/python3.11/site-packages
COPY app/ app/

# In-container cache (ephemeral on Cloud Run)
RUN mkdir -p /tmp/cache && chown app:app /tmp/cache
ENV CACHE_DB_PATH=/tmp/cache/cache.db

USER app
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 2.1 Cloud Run 고려사항

| 항목 | 값 | 이유 |
|------|-----|------|
| 포트 | `8080` | Cloud Run 기본 포트 |
| 캐시 경로 | `/tmp/cache/` | 인스턴스 재시작 시 초기화됨 (허용) |
| 사용자 | `app` (비root) | 보안 베스트 프랙티스 |

---

## 3. GitHub Actions Workflows

### 3.1 CI Workflow (`.github/workflows/ci.yml`)

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  workflow_call:

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        run: uv python install 3.11

      - name: Install dependencies
        run: uv sync --all-extras

      - name: Lint
        run: uv run ruff check .

      - name: Format check
        run: uv run ruff format --check .

      - name: Test
        run: uv run pytest -v
        env:
          GOOGLE_AI_API_KEY: "test-key"
          SUPABASE_URL: "https://test.supabase.co"
          SUPABASE_SERVICE_KEY: "test-key"
          API_KEY: "test-key"
```

### 3.2 Deploy Workflow (`.github/workflows/deploy.yml`)

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  ci:
    uses: ./.github/workflows/ci.yml

  deploy:
    needs: ci
    runs-on: ubuntu-latest
    concurrency: deploy-production
    permissions:
      contents: read
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}

      - name: Deploy to Cloud Run
        uses: google-github-actions/deploy-cloudrun@v2
        with:
          service: cognito-descriptor
          region: asia-northeast1
          source: .
          env_vars: |
            CORS_ORIGINS=["https://cognito.conaonda.com","http://localhost:5173"]
            LOG_LEVEL=INFO
            CACHE_DB_PATH=/tmp/cache/cache.db
          secrets: |
            GOOGLE_AI_API_KEY=GOOGLE_AI_API_KEY:latest
            SUPABASE_URL=SUPABASE_URL:latest
            SUPABASE_SERVICE_KEY=SUPABASE_SERVICE_KEY:latest
            API_KEY=DESCRIPTOR_API_KEY:latest
          flags: >-
            --allow-unauthenticated
            --memory=512Mi
            --cpu=1
            --min-instances=0
            --max-instances=2
            --concurrency=50
            --timeout=60s
```

### 3.3 워크플로우 흐름

```
PR 생성/업데이트
  │
  ▼
ci.yml ─── ruff check ─── ruff format --check ─── pytest
  │
  │ (PR merge to main)
  ▼
deploy.yml ─── ci ─── gcloud auth ─── deploy-cloudrun
  │
  ▼
Cloud Run ─── Docker build (Cloud Build) ─── Health check ─── Live
```

---

## 4. Secrets 관리

### 4.1 GitHub Secrets (Repository Settings)

| Secret | 용도 |
|--------|------|
| `WIF_PROVIDER` | Workload Identity Federation provider |
| `WIF_SERVICE_ACCOUNT` | GCP 서비스 계정 이메일 |

### 4.2 GCP Secret Manager

| Secret Name | 용도 |
|-------------|------|
| `GOOGLE_AI_API_KEY` | Gemini Vision API |
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | Supabase 서비스 키 |
| `DESCRIPTOR_API_KEY` | COGnito 프론트엔드 인증 |

### 4.3 초기 설정 순서 (수동, 1회)

```bash
# 1. GCP 프로젝트 설정
gcloud config set project YOUR_PROJECT_ID

# 2. 필요한 API 활성화
gcloud services enable run.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com

# 3. Secret Manager에 시크릿 저장
echo -n "your-key" | gcloud secrets create GOOGLE_AI_API_KEY --data-file=-
echo -n "your-url" | gcloud secrets create SUPABASE_URL --data-file=-
echo -n "your-key" | gcloud secrets create SUPABASE_SERVICE_KEY --data-file=-
echo -n "your-key" | gcloud secrets create DESCRIPTOR_API_KEY --data-file=-

# 4. Workload Identity Federation 설정 (GitHub Actions용)
# → GitHub Actions에서 GCP 인증을 위한 OIDC 설정
gcloud iam workload-identity-pools create github-pool \
  --location=global --display-name="GitHub Pool"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# 5. 서비스 계정 생성 + 권한
gcloud iam service-accounts create github-deployer \
  --display-name="GitHub Actions Deployer"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

# Cloud Run 서비스 계정에도 Secret 접근 권한
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# 6. WIF 바인딩
gcloud iam service-accounts add-iam-policy-binding \
  github-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/conaonda/ImageDescriptor"

# 7. GitHub Secrets 설정
# WIF_PROVIDER = projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider
# WIF_SERVICE_ACCOUNT = github-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

---

## 5. Project Structure (신규/변경 파일)

```
ImageDescriptor/
├── Dockerfile                        # MODIFIED: Cloud Run 포트 8080, /tmp 캐시
├── .github/
│   └── workflows/
│       ├── ci.yml                    # UNCHANGED
│       └── deploy.yml                # MODIFIED: Cloud Run 배포
├── .dockerignore                     # UNCHANGED
└── (기존 파일들...)
```

**삭제 파일**: `fly.toml` (불필요)

---

## 6. Implementation Order

1. [ ] `Dockerfile` 수정 (포트 8080, /tmp 캐시)
2. [ ] `fly.toml` 삭제
3. [ ] `.github/workflows/deploy.yml` Cloud Run으로 변경
4. [ ] GCP 프로젝트 + Secret Manager + WIF 설정 (수동, 가이드 제공)

---

## 7. Verification Checklist

- [ ] `docker build .` 로컬 빌드 성공
- [ ] PR 생성 시 `ci.yml` 자동 실행 (lint + test pass)
- [ ] main merge 시 `deploy.yml` 자동 실행
- [ ] `https://cognito-descriptor-XXXX.asia-northeast1.run.app/api/health` → `{"status": "ok"}`
- [ ] Secret Manager 시크릿이 Cloud Run에 주입됨
- [ ] 시크릿이 코드/로그에 노출되지 않음

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-26 | Initial design (Fly.io) | conaonda |
| 0.2 | 2026-02-27 | Changed to Cloud Run (cost $0) | conaonda |
