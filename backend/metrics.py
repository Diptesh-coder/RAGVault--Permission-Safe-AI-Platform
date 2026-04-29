"""Prometheus metrics for SentinelRAG ops monitoring.

Counters / histograms exposed at GET /api/metrics so prod ops can alert on
silent regressions (e.g., the streaming SDK falling back to pseudo-stream
because the Emergent proxy upstream changed).
"""
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Total successful streaming requests (any path: real or fallback)
stream_total = Counter(
    "sentinel_stream_total",
    "Total streaming chat completions served by /api/chat/stream",
)

# Increments only when llm_service.stream_answer falls back to pseudo-stream
stream_fallback_total = Counter(
    "sentinel_stream_fallback_total",
    "Streaming chat requests that fell back to pseudo-stream after a real-stream error",
)

# Time-to-first-token, measured inside llm_service.stream_answer
stream_first_token_seconds = Histogram(
    "sentinel_stream_first_token_seconds",
    "Wall-clock seconds from stream_answer entry to the first emitted chunk",
    buckets=(0.25, 0.5, 1.0, 2.0, 4.0, 6.0, 10.0, 20.0, 60.0),
)

# RBAC pre-filter — count denied/partial decisions so security ops can graph them
chat_decision_total = Counter(
    "sentinel_chat_decision_total",
    "Chat requests by access decision",
    ["decision"],
)

# Guardrail trigger counter
guardrail_triggered_total = Counter(
    "sentinel_guardrail_triggered_total",
    "Number of chat queries that matched a sensitive-pattern guardrail",
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
