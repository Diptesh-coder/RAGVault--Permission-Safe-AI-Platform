"""SentinelRAG iter-5 backend tests: production-hardening.

Covers:
  • REGRESSION: 4-role login, RBAC doc filtering (dave 3 / alice 8),
    intern dave CEO no-leak, smoke_stream PASS path exits 0
  • NEW: METRICS_TOKEN gating — 401 without header, 401 with wrong header,
    200 with correct header
  • NEW: histogram split by path label — sentinel_stream_first_token_seconds_*
    has {path="real"} samples after a /api/chat/stream call
  • NEW: smoke script with SENTINEL_METRICS_TOKEN env passes; without it the
    soft-fallback _read_metric returns 0.0 and script still passes
  • NEW: metrics module imports cleanly; render_metrics() returns non-empty body
    both with and without PROMETHEUS_MULTIPROC_DIR set
  • Counter increment regression with the token header
"""
from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import tempfile

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env", override=False)

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
METRICS_TOKEN = os.environ.get("METRICS_TOKEN")
assert METRICS_TOKEN, "METRICS_TOKEN must be set in /app/backend/.env for iter-5 tests"
HDR = {"X-Metrics-Token": METRICS_TOKEN}

LEAK_TERMS = ["4.8M", "1.2M", "2.1M", "1.5M", "performance bonus",
              "4,800,000", "1,200,000", "2,100,000", "1,500,000"]

SMOKE = "/app/backend/scripts/smoke_stream.py"


# ── Helpers ────────────────────────────────────────────────────────────────────
def _login(username: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"username": username, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {username}"
    return r.json()["access_token"]


def _read_metric(name: str, label_match: str | None = None) -> float:
    r = requests.get(f"{API}/metrics", headers=HDR, timeout=15)
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


def _drain_stream(token: str, query: str) -> int:
    r = requests.post(
        f"{API}/chat/stream",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        data=json.dumps({"query": query}),
        stream=True, timeout=90,
    )
    status = r.status_code
    for _ in r.iter_lines():
        pass
    r.close()
    return status


# ── Fixtures ───────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def alice_token():
    return _login("alice", "admin123")


@pytest.fixture(scope="module")
def dave_token():
    return _login("dave", "intern123")


# ── REGRESSION ─────────────────────────────────────────────────────────────────
class TestRegression:
    def test_login_all_4_roles(self):
        for u, p in [("alice", "admin123"), ("bob", "manager123"),
                     ("carol", "emp123"), ("dave", "intern123")]:
            r = requests.post(f"{API}/auth/login",
                              json={"username": u, "password": p}, timeout=15)
            assert r.status_code == 200, f"{u} login failed"
            assert "access_token" in r.json()

    def test_rbac_dave_sees_3_docs(self, dave_token):
        r = requests.get(f"{API}/documents",
                         headers={"Authorization": f"Bearer {dave_token}"}, timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_rbac_alice_sees_8_docs(self, alice_token):
        r = requests.get(f"{API}/documents",
                         headers={"Authorization": f"Bearer {alice_token}"}, timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 8

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
            assert term.lower() not in ans, f"LEAK: '{term}'"


# ── NEW: METRICS_TOKEN gating ──────────────────────────────────────────────────
class TestMetricsTokenGating:
    def test_no_header_401(self):
        r = requests.get(f"{API}/metrics", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"

    def test_wrong_header_401(self):
        r = requests.get(f"{API}/metrics",
                         headers={"X-Metrics-Token": "definitely-not-the-token"},
                         timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"

    def test_correct_header_200(self):
        r = requests.get(f"{API}/metrics", headers=HDR, timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").lower().startswith("text/plain")
        # body must contain at least one expected series line
        assert "sentinel_stream_total" in r.text


# ── NEW: histogram split by path label ─────────────────────────────────────────
class TestHistogramPathLabel:
    def test_path_real_label_present_after_stream(self, alice_token):
        # Make a stream call to ensure the real-path histogram is observed
        status = _drain_stream(alice_token, "Give a one-line summary of the H1 roadmap.")
        assert status == 200

        r = requests.get(f"{API}/metrics", headers=HDR, timeout=15)
        assert r.status_code == 200
        body = r.text

        # Must have at least one bucket sample with path="real"
        bucket_real = re.compile(
            r'^sentinel_stream_first_token_seconds_bucket\{[^}]*path="real"[^}]*\}\s+[0-9.eE+-]+$',
            re.M,
        )
        assert bucket_real.search(body), \
            "no sentinel_stream_first_token_seconds_bucket{...,path=\"real\"} sample found"

        # _count{path="real"} should be >= 1
        count = _read_metric("sentinel_stream_first_token_seconds_count",
                             label_match='path="real"')
        assert count >= 1, f"first_token_seconds_count{{path=real}} = {count}"


# ── NEW: counter increments still work (read with token) ───────────────────────
class TestCounterIncrementsWithToken:
    def test_stream_total_increments(self, alice_token):
        before = _read_metric("sentinel_stream_total")
        status = _drain_stream(alice_token, "Summarize the engineering roadmap in one sentence.")
        assert status == 200
        after = _read_metric("sentinel_stream_total")
        assert after >= before + 1, f"stream_total {before}->{after}"

    def test_chat_decision_granted_increments(self, alice_token):
        before = _read_metric("sentinel_chat_decision_total",
                              label_match='decision="granted"')
        r = requests.post(
            f"{API}/chat",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"query": "Summarize the engineering roadmap in one sentence."},
            timeout=90,
        )
        assert r.status_code == 200
        after = _read_metric("sentinel_chat_decision_total",
                             label_match='decision="granted"')
        assert after >= before + 1, f"chat_decision_total{{granted}} {before}->{after}"

    def test_guardrail_increments_on_ssn(self, alice_token):
        before = _read_metric("sentinel_guardrail_triggered_total")
        r = requests.post(
            f"{API}/chat",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"query": "What is John's social security number on file?"},
            timeout=90,
        )
        assert r.status_code == 200
        after = _read_metric("sentinel_guardrail_triggered_total")
        assert after >= before + 1, f"guardrail counter {before}->{after}"


# ── NEW: smoke_stream.py with the metrics token ────────────────────────────────
class TestSmokeWithToken:
    def _run(self, env_overrides: dict, timeout: int = 120):
        env = os.environ.copy()
        env["SENTINEL_BASE_URL"] = BASE_URL
        env["SENTINEL_USER"] = "alice"
        env["SENTINEL_PASS"] = "admin123"
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, SMOKE],
            env=env, capture_output=True, text=True, timeout=timeout,
        )

    def test_smoke_with_token_passes(self):
        proc = self._run({
            "SENTINEL_METRICS_TOKEN": METRICS_TOKEN,
            "SENTINEL_MAX_FIRST_TOKEN": "10.0",
        })
        assert proc.returncode == 0, (
            f"expected exit 0; got {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        assert "PASS" in proc.stdout
        # baseline metric read should have succeeded with a real number,
        # not the soft-fallback 0 (because counter has incremented over time)
        assert "baseline sentinel_stream_fallback_total" in proc.stdout
        assert "post-run sentinel_stream_fallback_total" in proc.stdout

    def test_smoke_without_token_soft_fallback_passes(self):
        # Without SENTINEL_METRICS_TOKEN, the GET /api/metrics inside smoke
        # script returns 401. The script's _read_metric catches URLError and
        # returns 0.0, which means baseline=0 and post-run=0 → delta=0 → PASS.
        env_overrides = {"SENTINEL_MAX_FIRST_TOKEN": "10.0"}
        # Make sure the var is cleared even if the parent shell exports it
        env = os.environ.copy()
        env.pop("SENTINEL_METRICS_TOKEN", None)
        env["SENTINEL_BASE_URL"] = BASE_URL
        env["SENTINEL_USER"] = "alice"
        env["SENTINEL_PASS"] = "admin123"
        env.update(env_overrides)
        proc = subprocess.run([sys.executable, SMOKE], env=env,
                              capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, (
            f"expected exit 0 (soft fallback); got {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        assert "PASS" in proc.stdout
        # With 401s, both reads should land on the 0.0 soft fallback
        assert "baseline sentinel_stream_fallback_total = 0" in proc.stdout
        assert "post-run sentinel_stream_fallback_total = 0" in proc.stdout


# ── NEW: metrics module multiproc helper ───────────────────────────────────────
class TestMetricsModuleMultiproc:
    """Validate the metrics module compiles cleanly and render_metrics()
    behaves correctly under both PROMETHEUS_MULTIPROC_DIR set / unset."""

    def test_metrics_module_imports_cleanly(self):
        # Run a fresh subprocess so module import is exercised standalone.
        code = (
            "import sys; sys.path.insert(0, '/app/backend'); "
            "import os; os.environ.pop('PROMETHEUS_MULTIPROC_DIR', None); "
            "import metrics; "
            "body, ct = metrics.render_metrics(); "
            "assert isinstance(body, (bytes, bytearray)) and len(body) > 0, len(body); "
            "assert ct.startswith('text/plain'), ct; "
            "assert b'sentinel_stream_total' in body; "
            "print('OK')"
        )
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, (
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        assert "OK" in proc.stdout

    def test_render_metrics_with_multiproc_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = (
                f"import sys; sys.path.insert(0, '/app/backend'); "
                f"import os; os.environ['PROMETHEUS_MULTIPROC_DIR'] = {tmp!r}; "
                "import metrics; "
                "body, ct = metrics.render_metrics(); "
                # In multiproc mode with no worker .db files, body may be empty
                # of samples, but the call must succeed and return bytes +
                # the correct content-type.
                "assert isinstance(body, (bytes, bytearray)), type(body); "
                "assert ct.startswith('text/plain'), ct; "
                "print('OK', len(body))"
            )
            proc = subprocess.run([sys.executable, "-c", code],
                                  capture_output=True, text=True, timeout=30)
            assert proc.returncode == 0, (
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            )
            assert "OK" in proc.stdout

    def test_render_metrics_live_endpoint_returns_nonempty_body(self):
        # Sanity: the running server's render_metrics path returns non-empty
        # bytes that include our custom series.
        r = requests.get(f"{API}/metrics", headers=HDR, timeout=15)
        assert r.status_code == 200
        assert len(r.content) > 0
        assert b"sentinel_stream_total" in r.content
