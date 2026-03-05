"""Prometheus metrics definitions for the Image Descriptor service."""

from prometheus_client import Counter, Gauge, Histogram

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

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    "circuit_breaker_open",
    "Circuit breaker state (1=open, 0=closed)",
    ["name"],
)
