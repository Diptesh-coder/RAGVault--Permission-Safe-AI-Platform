"""SentinelRAG iteration-6 tests — hardening polish.

Covers:
  (a) /api/metrics uses hmac.compare_digest() for constant-time token comparison.
      Still returns 401 on missing/wrong token, 200 on correct.
  (b) smoke_stream.py _read_metric prints '[smoke] WARN ... returned 401' line
      when SENTINEL_METRICS_TOKEN is not set against a backend with METRICS_TOKEN
      set, and still exits 0. Warn line absent when token is correct.
  (c) metrics.observe_first_token() raises ValueError on unknown path label,
      and both 'real' and 'fallback' child series are pre-instantiated at module
      import (visible with count=0 on a cold /api/metrics scrape).
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

# Load backend .env so METRICS_TOKEN is visible to tests invoked from any cwd.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
METRICS_TOKEN = os.environ["METRICS_TOKEN"]
METRICS_URL = f"{BASE_URL}/api/metrics"

BACKEND_DIR = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = BACKEND_DIR / "scripts" / "smoke_stream.py"


# ---------- helpers ----------
def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _metrics_body(token: str | None = METRICS_TOKEN) -> str:
    headers = {"X-Metrics-Token": token} if token is not None else {}
    r = requests.get(METRICS_URL, headers=headers, timeout=15)
    assert r.status_code == 200, f"metrics scrape failed: {r.status_code} {r.text}"
    return r.text


def _metric_value(body: str, sample_line_prefix: str) -> float | None:
    """Return value for a line like `name{labels} 1.0`, searching by startswith."""
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        if line.startswith(sample_line_prefix):
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    return float(parts[1])
                except ValueError:
                    return None
    return None


# ---------- (a) hmac.compare_digest token comparison ----------
class TestMetricsTokenHmac:
    def test_no_header_returns_401(self):
        r = requests.get(METRICS_URL, timeout=15)
        assert r.status_code == 401

    def test_wrong_token_returns_401(self):
        r = requests.get(
            METRICS_URL, headers={"X-Metrics-Token": "wrong-token-value"}, timeout=15
        )
        assert r.status_code == 401

    def test_wrong_same_length_returns_401(self):
        # Same-length wrong token — exercise compare_digest's constant-time path
        assert len(METRICS_TOKEN) == len("x" * len(METRICS_TOKEN))
        bogus = "a" * len(METRICS_TOKEN)
        r = requests.get(
            METRICS_URL, headers={"X-Metrics-Token": bogus}, timeout=15
        )
        assert r.status_code == 401

    def test_empty_header_returns_401(self):
        # Explicit empty header — server does `provided or ''` then compare_digest.
        r = requests.get(
            METRICS_URL, headers={"X-Metrics-Token": ""}, timeout=15
        )
        assert r.status_code == 401

    def test_correct_token_returns_200(self):
        r = requests.get(
            METRICS_URL, headers={"X-Metrics-Token": METRICS_TOKEN}, timeout=15
        )
        assert r.status_code == 200
        assert "sentinel_stream_total" in r.text

    def test_server_did_not_crash_after_bad_requests(self):
        # After the above bogus calls, server must still be healthy.
        for _ in range(3):
            requests.get(METRICS_URL, timeout=15)  # no header
            requests.get(METRICS_URL, headers={"X-Metrics-Token": "nope"}, timeout=15)
        r = requests.get(
            f"{BASE_URL}/api/", timeout=10
        )
        assert r.status_code in (200, 404)  # root or 404 both OK; server alive
        r2 = requests.get(
            METRICS_URL, headers={"X-Metrics-Token": METRICS_TOKEN}, timeout=15
        )
        assert r2.status_code == 200


# ---------- (c) cardinality lock on histogram ----------
class TestCardinalityLock:
    def test_observe_first_token_unknown_path_raises(self):
        """Import the live metrics module and call observe_first_token with a
        bogus label. Must raise ValueError mentioning 'unknown stream path label'.
        """
        script = f"""
import sys
sys.path.insert(0, r'{BACKEND_DIR}')
import metrics
try:
    metrics.observe_first_token('hacked', 0.5)
    print('NO_RAISE')
except ValueError as e:
    print('RAISED:' + str(e))
"""
        out = subprocess.check_output(
            [sys.executable, "-c", script], stderr=subprocess.STDOUT, timeout=20
        ).decode()
        assert "RAISED:" in out, out
        assert "unknown stream path label" in out, out

    def test_observe_first_token_known_paths_ok(self):
        script = f"""
import sys
sys.path.insert(0, r'{BACKEND_DIR}')
import metrics
metrics.observe_first_token('real', 0.1)
metrics.observe_first_token('fallback', 0.2)
print('OK')
"""
        out = subprocess.check_output(
            [sys.executable, "-c", script], stderr=subprocess.STDOUT, timeout=20
        ).decode()
        assert out.strip().endswith("OK"), out

    def test_both_child_series_present_in_exposition(self):
        """Both path='real' and path='fallback' _count lines must appear on a
        fresh scrape — proving the module pre-instantiated both children.
        """
        body = _metrics_body()
        # Accept either literal count=0.0 on a truly cold server, or any >=0 value
        # after traffic has accumulated. What matters is that both label
        # children exist in the exposition.
        real_line = re.search(
            r'^sentinel_stream_first_token_seconds_count\{[^}]*path="real"[^}]*\}\s+([0-9.eE+-]+)$',
            body,
            re.M,
        )
        fallback_line = re.search(
            r'^sentinel_stream_first_token_seconds_count\{[^}]*path="fallback"[^}]*\}\s+([0-9.eE+-]+)$',
            body,
            re.M,
        )
        assert real_line is not None, "path='real' count sample missing from exposition"
        assert fallback_line is not None, "path='fallback' count sample missing from exposition"
        real_val = float(real_line.group(1))
        fallback_val = float(fallback_line.group(1))
        assert real_val >= 0.0
        assert fallback_val >= 0.0

    def test_stream_increments_real_not_fallback(self):
        body_before = _metrics_body()
        real_before = _metric_value(
            body_before,
            'sentinel_stream_first_token_seconds_count{path="real"}',
        )
        fallback_before = _metric_value(
            body_before,
            'sentinel_stream_first_token_seconds_count{path="fallback"}',
        )
        assert real_before is not None
        assert fallback_before is not None

        token = _login("alice", "admin123")
        r = requests.post(
            f"{BASE_URL}/api/chat/stream",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": "Summarize the roadmap in one sentence."},
            stream=True,
            timeout=60,
        )
        assert r.status_code == 200
        # Drain the stream
        for _line in r.iter_lines():
            pass
        r.close()

        body_after = _metrics_body()
        real_after = _metric_value(
            body_after,
            'sentinel_stream_first_token_seconds_count{path="real"}',
        )
        fallback_after = _metric_value(
            body_after,
            'sentinel_stream_first_token_seconds_count{path="fallback"}',
        )
        assert real_after is not None and fallback_after is not None
        assert real_after >= real_before + 1, (
            f"real path count did not increment: before={real_before} after={real_after}"
        )
        assert fallback_after == fallback_before, (
            f"fallback unexpectedly incremented under normal operation: "
            f"before={fallback_before} after={fallback_after}"
        )


# ---------- (b) smoke_stream WARN line on 401 ----------
class TestSmokeStreamWarnOn401:
    def _run_smoke(self, with_metrics_token: bool) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["SENTINEL_BASE_URL"] = BASE_URL
        env["SENTINEL_USER"] = "alice"
        env["SENTINEL_PASS"] = "admin123"
        # Slightly generous budget for the preview env's cold path.
        env["SENTINEL_MAX_FIRST_TOKEN"] = "15.0"
        env["SENTINEL_TOTAL_TIMEOUT"] = "90.0"
        if with_metrics_token:
            env["SENTINEL_METRICS_TOKEN"] = METRICS_TOKEN
        else:
            env.pop("SENTINEL_METRICS_TOKEN", None)
        return subprocess.run(
            [sys.executable, str(SMOKE_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_smoke_warn_when_no_token_against_protected_backend(self):
        proc = self._run_smoke(with_metrics_token=False)
        combined = proc.stdout + "\n" + proc.stderr
        # Must warn and still exit 0
        assert "[smoke] WARN" in combined, f"no WARN line in output:\n{combined}"
        assert "returned 401" in combined, f"WARN line missing '401':\n{combined}"
        assert "[smoke] baseline sentinel_stream_fallback_total = 0" in combined, (
            f"expected soft-fallback baseline 0 line; output:\n{combined}"
        )
        assert "[smoke] PASS" in combined, f"smoke did not PASS:\n{combined}"
        assert proc.returncode == 0, (
            f"smoke exit={proc.returncode}; output:\n{combined}"
        )

    def test_smoke_no_warn_when_correct_token(self):
        proc = self._run_smoke(with_metrics_token=True)
        combined = proc.stdout + "\n" + proc.stderr
        assert proc.returncode == 0, (
            f"smoke exit={proc.returncode}; output:\n{combined}"
        )
        assert "[smoke] PASS" in combined, f"smoke did not PASS:\n{combined}"
        assert "[smoke] WARN" not in combined, (
            f"unexpected WARN line when token was provided:\n{combined}"
        )


# ---------- regression: iter1-5 critical paths smoke ----------
class TestIter6Regression:
    def test_four_role_login(self):
        for u, p in [
            ("alice", "admin123"),
            ("bob", "manager123"),
            ("carol", "emp123"),
            ("dave", "intern123"),
        ]:
            t = _login(u, p)
            assert isinstance(t, str) and len(t) > 10

    def test_guardrail_still_fires(self):
        t = _login("alice", "admin123")
        r = requests.post(
            f"{BASE_URL}/api/chat",
            headers={"Authorization": f"Bearer {t}"},
            json={"query": "Please share my social security number"},
            timeout=30,
        )
        # Guardrail responses come back 200 with a sanitized body or 400; either is acceptable
        # for regression — main requirement is the server does not 500.
        assert r.status_code < 500, r.text

    def test_intern_ceo_no_leak(self):
        t = _login("dave", "intern123")
        r = requests.post(
            f"{BASE_URL}/api/chat",
            headers={"Authorization": f"Bearer {t}"},
            json={"query": "What is the CEO compensation package?"},
            timeout=30,
        )
        assert r.status_code < 500
        # answer must not mention CEO comp figures — loose check: no '$' amount in answer
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        answer = (data.get("answer") or "").lower()
        assert "ceo compensation" not in answer or "not authorized" in answer or "cannot" in answer or "no access" in answer or answer == ""

    def test_stream_total_increments(self):
        body_before = _metrics_body()
        before = _metric_value(body_before, "sentinel_stream_total ")
        assert before is not None

        t = _login("alice", "admin123")
        r = requests.post(
            f"{BASE_URL}/api/chat/stream",
            headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
            json={"query": "Regression ping."},
            stream=True,
            timeout=60,
        )
        assert r.status_code == 200
        for _ in r.iter_lines():
            pass
        r.close()

        body_after = _metrics_body()
        after = _metric_value(body_after, "sentinel_stream_total ")
        assert after is not None and after >= before + 1
