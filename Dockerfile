# ── Build Stage ──
FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# Remove __pycache__ and .pyc from venv
RUN find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    find /app/.venv -name "*.pyc" -delete 2>/dev/null; \
    find /app/.venv -name "*.pyo" -delete 2>/dev/null; \
    true

# ── Runtime Stage ──
FROM python:3.11-alpine

RUN addgroup -S app && adduser -S -G app -h /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app/ app/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1

# In-container cache (ephemeral on Cloud Run)
RUN mkdir -p /tmp/cache && chown app:app /tmp/cache
ENV CACHE_DB_PATH=/tmp/cache/cache.db

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health/live')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
