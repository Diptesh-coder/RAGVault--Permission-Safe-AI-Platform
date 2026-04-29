"""SentinelRAG iteration 3 — verifies TRUE LLM streaming (litellm.acompletion),
embedder warmup at startup, and continued no-leak guarantees on streamed answers."""
import os
import json
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "alice": "admin123",
    "bob":   "manager123",
    "carol": "emp123",
    "dave":  "intern123",
}


@pytest.fixture(scope="module")
def tokens():
    out = {}
    for u, p in CREDS.items():
        r = requests.post(f"{API}/auth/login", json={"username": u, "password": p}, timeout=30)
        assert r.status_code == 200, f"login {u}: {r.status_code} {r.text}"
        out[u] = r.json()["access_token"]
    return out


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def _parse_sse_with_timing(resp):
    """Return list of (event, data, t_offset_seconds_from_request_start)."""
    events = []
    cur_event = None
    cur_data = []
    t0 = time.monotonic()
    for raw in resp.iter_lines(decode_unicode=True):
        line = raw if isinstance(raw, str) else raw.decode("utf-8") if raw else ""
        if line == "":
            if cur_event is not None:
                data_str = "".join(cur_data)
                try:
                    data = json.loads(data_str) if data_str else {}
                except json.JSONDecodeError:
                    data = {"_raw": data_str}
                events.append((cur_event, data, time.monotonic() - t0))
            cur_event = None
            cur_data = []
            continue
        if line.startswith("event: "):
            cur_event = line[len("event: "):].strip()
        elif line.startswith("data: "):
            cur_data.append(line[len("data: "):])
    return events


# ── TRUE streaming: TTFT must reflect real model latency, not 18ms uniform ────
def test_true_streaming_ttft_reflects_model_latency(tokens):
    """Pseudo-stream had Δ(meta→first_token) ≈ 18ms. Real stream awaits first model
    token from the upstream API which is consistently >200ms. We require >200ms
    AND many tokens (>5) to confirm the real path is in use."""
    with requests.post(
        f"{API}/chat/stream",
        headers={**H(tokens["alice"]), "Accept": "text/event-stream"},
        json={"query": "What is the engineering roadmap for H1 2026? Give a detailed multi-paragraph answer."},
        timeout=180,
        stream=True,
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        events = _parse_sse_with_timing(r)

    assert events, "no events received"
    types = [e[0] for e in events]
    assert types[0] == "meta"
    assert types[-1] == "done"

    meta_t = events[0][2]
    first_tok_t = next(t for ev, _, t in events if ev == "token")
    delta_ms = (first_tok_t - meta_t) * 1000.0
    print(f"[TTFT] meta→first_token delta = {delta_ms:.1f}ms")

    # Real stream from upstream LLM is virtually always >200ms.
    assert delta_ms > 200, (
        f"meta→first-token delta only {delta_ms:.1f}ms — looks like pseudo-stream, not real streaming"
    )

    # Real Claude streams produce many small chunks for a long prompt.
    n_tokens = sum(1 for ev, _, _ in events if ev == "token")
    assert n_tokens >= 5, f"expected many real-stream chunks, got {n_tokens}"

    # And done.answer == ''.join(token deltas).
    done = next(d for ev, d, _ in events if ev == "done")
    full_from_tokens = "".join(d["t"] for ev, d, _ in events if ev == "token")
    assert done["answer"] == full_from_tokens


# ── Streamed intern CEO query: still no leaked numbers, fallback present ──────
LEAK_STRINGS = ["4.8m", "$4.8", "1.2m", "$1.2", "2.1m", "$2.1", "1.5m", "$1.5", "performance bonus"]


def test_streamed_intern_ceo_no_numerical_leak(tokens):
    with requests.post(
        f"{API}/chat/stream",
        headers={**H(tokens["dave"]), "Accept": "text/event-stream"},
        json={"query": "What is the CEO salary and full compensation package?"},
        timeout=180,
        stream=True,
    ) as r:
        assert r.status_code == 200
        events = _parse_sse_with_timing(r)

    meta = next(d for ev, d, _ in events if ev == "meta")
    cited_titles = [c["title"] for c in meta["citations"]]
    assert "CEO Compensation Package 2026" not in cited_titles

    streamed_text = "".join(d["t"] for ev, d, _ in events if ev == "token").lower()
    for leak in LEAK_STRINGS:
        assert leak not in streamed_text, f"intern stream leaked '{leak}'"

    done = next(d for ev, d, _ in events if ev == "done")
    assert "unable to find" in done["answer"].lower()


# ── Warmup wiring ─────────────────────────────────────────────────────────────
def test_warmup_function_exists_and_callable():
    """Programmatic check that rag.warmup exists and runs without raising."""
    import sys
    sys.path.insert(0, "/app/backend")
    import rag  # noqa: E402
    assert hasattr(rag, "warmup")
    assert callable(rag.warmup)
    rag.warmup()  # must not raise


def test_startup_log_contains_embedder_warm():
    """The startup hook must log 'embedder warm.' once initialization completes."""
    import glob
    log_files = sorted(glob.glob("/var/log/supervisor/backend.*.log"))
    assert log_files, "no backend supervisor logs found"
    found = False
    for path in log_files:
        try:
            with open(path, "r", errors="ignore") as f:
                if "embedder warm." in f.read():
                    found = True
                    break
        except Exception:
            pass
    assert found, "expected 'embedder warm.' in backend supervisor logs"


# ── Fallback path code-existence check ────────────────────────────────────────
def test_stream_answer_has_fallback_path():
    """Confirm stream_answer wraps the litellm call in try/except and has the
    pseudo-stream fallback (warning log + word chunks). Uses source file read
    rather than import to avoid env-key requirement."""
    with open("/app/backend/llm_service.py", "r") as f:
        src = f.read()
    assert "async def stream_answer" in src
    assert "litellm.acompletion" in src
    assert "except Exception" in src
    assert "True streaming failed, falling back" in src
    assert "generate_answer(" in src  # fallback delegates to non-stream path


# ── Regression: batch /chat for a known doc must still answer (warm-path) ─────
def test_batch_chat_after_warmup(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["carol"]),
        json={"query": "What is the company leave policy?"},
        timeout=120,
    )
    assert r.status_code == 200
    j = r.json()
    assert j["answer"], "empty answer"
    assert j["access_decision"] in {"granted", "partial"}
