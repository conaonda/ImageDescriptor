"""Prometheus metrics definitions for the Image Descriptor service."""

from prometheus_client import Counter, Gauge, Histogram

# Description request metrics
description_requests_total = Counter(
    "description_requests_total",
    "Total description generation requests",
    ["status"],
)

# External API call metrics
external_api_requests = Counter(
    "external_api_requests_total",
    "Total external API calls",
    ["service", "status"],
)

external_api_duration = Histogram(
    "external_api_duration_seconds",
    "External API call duration",
    ["service"],
)

# Cache metrics
cache_hits = Counter(
    "cache_hits_total",
    "Total cache hits",
    ["module"],
)

cache_misses = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["module"],
)

cache_cleanup_total = Counter(
    "cache_cleanup_total",
    "Total expired cache entries removed",
)

# Circuit breaker metrics (0=closed, 1=open, 2=half-open)
circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    ["name"],
)

# Batch job metrics
active_batch_jobs = Gauge(
    "active_batch_jobs",
    "Number of currently running batch jobs",
)
