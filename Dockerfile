# ── Build Stage ──
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --target=/deps .

# ── Runtime Stage ──
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
