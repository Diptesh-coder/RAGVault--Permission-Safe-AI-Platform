#!/usr/bin/env python3
"""SentinelRAG streaming smoke test — designed for a CI cron.

Hard-fails (exit 1) if either:
  • the first SSE chunk does not arrive within MAX_FIRST_TOKEN_SECONDS, or
  • Prometheus metric `sentinel_stream_fallback_total` increments during the run
    (i.e. the real-stream path silently fell back to pseudo-stream).

Usage:
    SENTINEL_BASE_URL=https://… SENTINEL_USER=alice SENTINEL_PASS=admin123 \
        python3 backend/scripts/smoke_stream.py
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("SENTINEL_BASE_URL", "http://localhost:8001").rstrip("/")
USER = os.environ.get("SENTINEL_USER", "alice")
PASS = os.environ.get("SENTINEL_PASS", "admin123")
QUERY = os.environ.get(
    "SENTINEL_SMOKE_QUERY",
    "Summarize the engineering roadmap for H1 2026 in one sentence.",
)
MAX_FIRST_TOKEN_SECONDS = float(os.environ.get("SENTINEL_MAX_FIRST_TOKEN", "6.0"))
TOTAL_TIMEOUT_SECONDS = float(os.environ.get("SENTINEL_TOTAL_TIMEOUT", "60.0"))


def _http(method: str, path: str, *, headers=None, body: bytes | None = None, timeout=30):
    h = {"User-Agent": "SentinelRAG-SmokeTest/1.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(f"{BASE}{path}", method=method, headers=h, data=body)
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310


def _login() -> str:
    body = json.dumps({"username": USER, "password": PASS}).encode()
    with _http("POST", "/api/auth/login",
               headers={"Content-Type": "application/json"}, body=body) as r:
        return json.loads(r.read())["access_token"]


def _read_metric(name: str) -> float:
    try:
        with _http("GET", "/api/metrics") as r:
            text = r.read().decode()
    except urllib.error.URLError:
        return 0.0
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        m = re.match(rf"^{re.escape(name)}(?:\{{[^}}]*\}})?\s+([0-9.eE+-]+)$", line)
        if m:
            return float(m.group(1))
    return 0.0


def main() -> int:
    print(f"[smoke] base={BASE} user={USER} max_first_token={MAX_FIRST_TOKEN_SECONDS}s")
    fallback_before = _read_metric("sentinel_stream_fallback_total")
    print(f"[smoke] baseline sentinel_stream_fallback_total = {fallback_before:.0f}")

    token = _login()
    body = json.dumps({"query": QUERY}).encode()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    t0 = time.perf_counter()
    first_token_at: float | None = None
    saw_done = False
    saw_meta = False

    try:
        resp = _http("POST", "/api/chat/stream",
                     headers=headers, body=body, timeout=TOTAL_TIMEOUT_SECONDS)
    except urllib.error.URLError as e:
        print(f"[smoke] FAIL — could not connect: {e}")
        return 1

    current_event = "message"
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            now = time.perf_counter()
            if current_event == "meta":
                saw_meta = True
            elif current_event == "token" and first_token_at is None:
                first_token_at = now - t0
                print(f"[smoke] first token at {first_token_at:.2f}s")
            elif current_event == "done":
                saw_done = True
                break
            elif current_event == "error":
                print(f"[smoke] FAIL — server emitted error event: {line}")
                return 1

    elapsed = time.perf_counter() - t0
    print(f"[smoke] total stream duration = {elapsed:.2f}s, meta={saw_meta} done={saw_done}")

    if first_token_at is None:
        print("[smoke] FAIL — no token chunk received from /api/chat/stream")
        return 1
    if first_token_at > MAX_FIRST_TOKEN_SECONDS:
        print(
            f"[smoke] FAIL — first token took {first_token_at:.2f}s "
            f"(> {MAX_FIRST_TOKEN_SECONDS:.1f}s budget)"
        )
        return 1

    fallback_after = _read_metric("sentinel_stream_fallback_total")
    print(f"[smoke] post-run sentinel_stream_fallback_total = {fallback_after:.0f}")
    if fallback_after > fallback_before:
        delta = fallback_after - fallback_before
        print(
            f"[smoke] FAIL — stream_fallback_total incremented by {delta:.0f} "
            f"(real-stream path silently fell back to pseudo-stream)"
        )
        return 1

    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
