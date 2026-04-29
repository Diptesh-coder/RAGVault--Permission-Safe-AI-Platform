"""Prometheus metrics for SentinelRAG ops monitoring.

Multi-process aware: when PROMETHEUS_MULTIPROC_DIR is set, render_metrics()
aggregates counters across all uvicorn/gunicorn workers via the standard
prometheus_client multiprocess collector.
"""
import os
from prometheus_client import (
    Counter, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
    multiprocess,
)


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

# Time-to-first-token, labeled by code path so SLO graphs do not mix the two.
# Cardinality guardrail: `path` is fixed to the values in VALID_STREAM_PATHS so
# a stray developer can't blow up the series count by inventing new labels.
VALID_STREAM_PATHS = ("real", "fallback")

stream_first_token_seconds = Histogram(
    "sentinel_stream_first_token_seconds",
    "Wall-clock seconds from stream_answer entry to the first emitted chunk",
    labelnames=("path",),
    buckets=(0.25, 0.5, 1.0, 2.0, 4.0, 6.0, 10.0, 20.0, 60.0),
)


def observe_first_token(path: str, value: float) -> None:
    """Record a TTFT sample under one of the enumerated `path` labels.

    Raises ValueError on unknown paths so cardinality stays bounded at exactly
    len(VALID_STREAM_PATHS) child series. Pre-create the children at import
    time so the labelled bucket lines always appear in the exposition.
    """
    if path not in VALID_STREAM_PATHS:
        raise ValueError(
            f"unknown stream path label '{path}'; expected one of {VALID_STREAM_PATHS}"
        )
    stream_first_token_seconds.labels(path=path).observe(value)


# Pre-create the bounded child series so cardinality is locked at module load.
for _p in VALID_STREAM_PATHS:
    stream_first_token_seconds.labels(path=_p)

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
    """Return (body, content_type) for the /api/metrics response.

    If PROMETHEUS_MULTIPROC_DIR is set, aggregate across worker processes.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


# ── In-process snapshot helpers (used by /api/admin/ops) ──────────────────────
def _histogram_quantile(q: float, buckets: list[tuple[float, float]]) -> float:
    """Linear-interpolation quantile over cumulative-count histogram buckets.

    buckets: list of (le, cumulative_count) sorted by `le` ascending. The +Inf
    bucket may be present as le == float('inf').
    """
    if not buckets:
        return 0.0
    total = buckets[-1][1]
    if total <= 0:
        return 0.0
    target = q * total
    prev_le, prev_cnt = 0.0, 0.0
    for le, cnt in buckets:
        if cnt >= target:
            if le == float("inf"):
                return prev_le
            if cnt == prev_cnt:
                return le
            return prev_le + (le - prev_le) * (target - prev_cnt) / (cnt - prev_cnt)
        prev_le, prev_cnt = le, cnt
    return buckets[-1][0]


def snapshot() -> dict:
    """Walk the Prometheus registry once and return a JSON-friendly dict of KPIs.

    Computed in-process so the frontend never needs to know METRICS_TOKEN.
    """
    counters: dict[str, float] = {}
    decisions: dict[str, float] = {"granted": 0.0, "partial": 0.0, "denied": 0.0}
    hist_buckets: dict[str, list[tuple[float, float]]] = {"real": [], "fallback": []}
    hist_count: dict[str, float] = {"real": 0.0, "fallback": 0.0}

    body, _ = render_metrics()
    for raw in body.decode("utf-8", errors="replace").splitlines():
        if not raw or raw.startswith("#"):
            continue
        # name{labels} value   OR   name value
        try:
            name_part, value_str = raw.rsplit(" ", 1)
            value = float(value_str)
        except ValueError:
            continue

        name = name_part.split("{", 1)[0]
        labels: dict[str, str] = {}
        if "{" in name_part:
            label_blob = name_part.split("{", 1)[1].rstrip("}")
            for pair in label_blob.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    labels[k.strip()] = v.strip().strip('"')

        if name in (
            "sentinel_stream_total", "sentinel_stream_fallback_total",
            "sentinel_guardrail_triggered_total",
        ):
            counters[name] = max(counters.get(name, 0.0), value)
        elif name == "sentinel_chat_decision_total":
            d = labels.get("decision")
            if d in decisions:
                decisions[d] = max(decisions[d], value)
        elif name == "sentinel_stream_first_token_seconds_bucket":
            path = labels.get("path")
            le = labels.get("le")
            if path in hist_buckets and le is not None:
                le_f = float("inf") if le == "+Inf" else float(le)
                hist_buckets[path].append((le_f, value))
        elif name == "sentinel_stream_first_token_seconds_count":
            path = labels.get("path")
            if path in hist_count:
                hist_count[path] = value

    for path in hist_buckets:
        hist_buckets[path].sort(key=lambda t: t[0])

    stream_total = counters.get("sentinel_stream_total", 0.0)
    fallback_total = counters.get("sentinel_stream_fallback_total", 0.0)
    guardrail_total = counters.get("sentinel_guardrail_triggered_total", 0.0)
    granted = decisions["granted"]
    denied = decisions["denied"]

    return {
        "ttft_p95_real": _histogram_quantile(0.95, hist_buckets["real"]),
        "ttft_p95_fallback": _histogram_quantile(0.95, hist_buckets["fallback"]),
        "ttft_observations_real": hist_count["real"],
        "ttft_observations_fallback": hist_count["fallback"],
        "stream_total": stream_total,
        "stream_fallback_total": fallback_total,
        "fallback_rate": (fallback_total / stream_total) if stream_total else 0.0,
        "decisions": decisions,
        "denied_to_granted_ratio": (denied / granted) if granted else 0.0,
        "guardrail_total": guardrail_total,
    }
