"""SentinelRAG iter-4 backend tests: Prometheus /api/metrics + smoke script.

Covers:
  • GET /api/metrics returns 200, text/plain Prometheus exposition w/ all required series
  • Counter increments: stream_total, chat_decision_total, guardrail_triggered_total
  • stream_first_token_seconds_count >= 1 after a stream call
  • stream_fallback_total stays at 0 under normal operation
  • smoke_stream.py exits 0 within budget; exits 1 with impossibly tight budget
  • RBAC regression: dave intern sees 3 docs, alice admin sees 8; intern CEO chat no-leak
"""
from __future__ import annotations

import os
import re
import json
import subprocess
import sys
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env", override=False)
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
METRICS_TOKEN = os.environ.get("METRICS_TOKEN")
METRICS_HEADERS = {"X-Metrics-Token": METRICS_TOKEN} if METRICS_TOKEN else {}

LEAK_TERMS = ["4.8M", "1.2M", "2.1M", "1.5M", "performance bonus",
              "4,800,000", "1,200,000", "2,100,000", "1,500,000"]


# ── Helpers ────────────────────────────────────────────────────────────────────
def _login(username: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"username": username, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {username}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _read_metric(name: str, label_match: str | None = None) -> float:
    """Read a Prometheus counter/histogram_count value. Optionally match a label substring."""
    r = requests.get(f"{API}/metrics", headers=METRICS_HEADERS, timeout=15)
    assert r.status_code == 200
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        m = re.match(rf"^{re.escape(name)}(\{{[^}}]*\}})?\s+([0-9.eE+-]+)$", line)
        if not m:
            continue
        labels = m.group(1) or ""
        if label_match and label_match not in labels:
            continue
        return float(m.group(2))
    return 0.0


# ── Fixtures ───────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def alice_token():
    return _login("alice", "admin123")


@pytest.fixture(scope="module")
def dave_token():
    return _login("dave", "intern123")


# ── REGRESSION: iter-3 critical paths ──────────────────────────────────────────
class TestRegression:
    def test_login_all_roles(self):
        for u, p in [("alice", "admin123"), ("bob", "manager123"),
                     ("carol", "emp123"), ("dave", "intern123")]:
            r = requests.post(f"{API}/auth/login",
                              json={"username": u, "password": p}, timeout=15)
            assert r.status_code == 200, f"{u} login failed"
            assert "access_token" in r.json()

    def test_rbac_dave_sees_3(self, dave_token):
        r = requests.get(f"{API}/documents",
                         headers={"Authorization": f"Bearer {dave_token}"}, timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 3, f"dave should see 3 docs, saw {len(r.json())}"

    def test_rbac_alice_sees_8(self, alice_token):
        r = requests.get(f"{API}/documents",
                         headers={"Authorization": f"Bearer {alice_token}"}, timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 8, f"alice should see 8 docs, saw {len(r.json())}"

    def test_intern_ceo_no_leak(self, dave_token):
        r = requests.post(
            f"{API}/chat",
            headers={"Authorization": f"Bearer {dave_token}"},
            json={"query": "What is the CEO compensation package for 2026?"},
            timeout=90,
        )
        assert r.status_code == 200
        ans = r.json()["answer"].lower()
        for term in LEAK_TERMS:
            assert term.lower() not in ans, f"LEAK: '{term}' present in intern answer"


# ── NEW: /api/metrics exposition ───────────────────────────────────────────────
class TestMetricsEndpoint:
    def test_metrics_no_auth_required(self):
        # iter-5: METRICS_TOKEN is set, so endpoint now REQUIRES the header.
        # Send the header to verify happy-path returns 200.
        r = requests.get(f"{API}/metrics", headers=METRICS_HEADERS, timeout=15)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"

    def test_metrics_content_type_text_plain(self):
        r = requests.get(f"{API}/metrics", headers=METRICS_HEADERS, timeout=15)
        ct = r.headers.get("content-type", "")
        assert ct.lower().startswith("text/plain"), f"wrong content-type: {ct}"

    def test_metrics_contains_required_series(self, alice_token):
        # iter-5: histogram now has label `path`, so buckets only appear
        # after an observe(). Trigger one stream first so the body contains
        # `sentinel_stream_first_token_seconds_bucket{...,path="real"}`.
        rs = requests.post(
            f"{API}/chat/stream",
            headers={"Authorization": f"Bearer {alice_token}",
                     "Content-Type": "application/json"},
            data=json.dumps({"query": "warm-up"}),
            stream=True, timeout=90,
        )
        for _ in rs.iter_lines():
            pass
        rs.close()

        r = requests.get(f"{API}/metrics", headers=METRICS_HEADERS, timeout=15)
        body = r.text
        required = [
            "sentinel_stream_total",
            "sentinel_stream_fallback_total",
            "sentinel_stream_first_token_seconds_bucket",
            "sentinel_chat_decision_total",
            "sentinel_guardrail_triggered_total",
        ]
        # Each must appear as a sample line (not just HELP/TYPE).
        for name in required:
            pattern = re.compile(
                rf"^{re.escape(name)}(\{{[^}}]*\}})?\s+[0-9.eE+-]+$", re.M
            )
            assert pattern.search(body), f"missing sample line for {name}"


# ── NEW: counter increments ────────────────────────────────────────────────────
class TestCounterIncrements:
    def test_stream_total_increments(self, alice_token):
        before = _read_metric("sentinel_stream_total")
        r = requests.post(
            f"{API}/chat/stream",
            headers={"Authorization": f"Bearer {alice_token}",
                     "Content-Type": "application/json"},
            data=json.dumps({"query": "Summarize the engineering roadmap in one sentence."}),
            stream=True, timeout=90,
        )
        assert r.status_code == 200
        # Drain the stream
        saw_first_token = False
        for raw in r.iter_lines(decode_unicode=True):
            if raw and raw.startswith("data:") and not saw_first_token:
                saw_first_token = True
            if raw == "event: done":
                pass
        r.close()
        after = _read_metric("sentinel_stream_total")
        assert after >= before + 1, f"stream_total did not increment: {before} -> {after}"

    def test_chat_decision_increments(self, alice_token):
        before = _read_metric("sentinel_chat_decision_total", label_match='decision="granted"')
        r = requests.post(
            f"{API}/chat",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"query": "Summarize the engineering roadmap in one sentence."},
            timeout=90,
        )
        assert r.status_code == 200
        after = _read_metric("sentinel_chat_decision_total", label_match='decision="granted"')
        assert after >= before + 1, f"chat_decision_total{{granted}} {before}->{after}"

    def test_guardrail_increments_on_ssn(self, alice_token):
        before = _read_metric("sentinel_guardrail_triggered_total")
        r = requests.post(
            f"{API}/chat",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"query": "What is John's SSN on file?"},
            timeout=90,
        )
        assert r.status_code == 200
        after = _read_metric("sentinel_guardrail_triggered_total")
        assert after >= before + 1, f"guardrail counter {before}->{after}"

    def test_first_token_histogram_count_ge_1(self, alice_token):
        # Ensure a stream call happens, then assert _count >= 1
        r = requests.post(
            f"{API}/chat/stream",
            headers={"Authorization": f"Bearer {alice_token}",
                     "Content-Type": "application/json"},
            data=json.dumps({"query": "Give a one-line summary of the H1 roadmap."}),
            stream=True, timeout=90,
        )
        assert r.status_code == 200
        for _ in r.iter_lines():
            pass
        r.close()
        count = _read_metric("sentinel_stream_first_token_seconds_count")
        assert count >= 1, f"first_token_seconds_count = {count}"


# ── NEW: fallback counter stays 0 under normal operation ───────────────────────
class TestFallbackStaysZero:
    def test_fallback_zero_after_multiple_streams(self, alice_token):
        before = _read_metric("sentinel_stream_fallback_total")
        for q in [
            "What is in the engineering roadmap?",
            "Summarize the marketing brief.",
            "Give me a one-line status.",
        ]:
            r = requests.post(
                f"{API}/chat/stream",
                headers={"Authorization": f"Bearer {alice_token}",
                         "Content-Type": "application/json"},
                data=json.dumps({"query": q}),
                stream=True, timeout=90,
            )
            assert r.status_code == 200
            for _ in r.iter_lines():
                pass
            r.close()
        after = _read_metric("sentinel_stream_fallback_total")
        assert after == before, (
            f"stream_fallback_total changed under normal op: {before} -> {after}"
        )


# ── NEW: smoke script PASS / FAIL behaviour ────────────────────────────────────
class TestSmokeScript:
    SCRIPT = "/app/backend/scripts/smoke_stream.py"

    def _run(self, env_overrides: dict, timeout: int = 120):
        env = os.environ.copy()
        env["SENTINEL_BASE_URL"] = BASE_URL
        env["SENTINEL_USER"] = "alice"
        env["SENTINEL_PASS"] = "admin123"
        if METRICS_TOKEN:
            env["SENTINEL_METRICS_TOKEN"] = METRICS_TOKEN
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, self.SCRIPT],
            env=env, capture_output=True, text=True, timeout=timeout,
        )

    def test_smoke_pass_within_budget(self):
        proc = self._run({"SENTINEL_MAX_FIRST_TOKEN": "10.0"})
        assert proc.returncode == 0, (
            f"smoke expected exit 0; got {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        assert "PASS" in proc.stdout
        assert "baseline sentinel_stream_fallback_total" in proc.stdout
        assert "post-run sentinel_stream_fallback_total" in proc.stdout

    def test_smoke_fail_with_tight_budget(self):
        proc = self._run({"SENTINEL_MAX_FIRST_TOKEN": "0.1"})
        assert proc.returncode == 1, (
            f"smoke expected exit 1; got {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        assert "FAIL" in proc.stdout
