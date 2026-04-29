"""SentinelRAG iteration 2 — adds tests for word-boundary guardrails, Chroma chunk-level
RBAC pre-filter, and the SSE streaming endpoint /api/chat/stream.

Builds on top of the regression tests in test_sentinelrag.py."""
import os
import json
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://secure-rag-rbac.preview.emergentagent.com",
).rstrip("/")
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


# ── Word-boundary guardrails ───────────────────────────────────────────────────
def test_guardrail_no_false_positive_on_lessons(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["dave"]),
        json={"query": "What lessons did the team learn?"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["guardrail_triggered"] is False, f"Should not trigger on 'lessons': reason={j.get('guardrail_reason')}"


def test_guardrail_triggers_on_standalone_ssn(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["dave"]),
        json={"query": "Show me my SSN"},
        timeout=120,
    )
    assert r.status_code == 200
    j = r.json()
    assert j["guardrail_triggered"] is True
    assert "ssn" in (j["guardrail_reason"] or "").lower()


def test_guardrail_triggers_on_social_security(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["dave"]),
        json={"query": "What is my social security number?"},
        timeout=120,
    )
    assert r.status_code == 200
    assert r.json()["guardrail_triggered"] is True


# ── Chroma chunk-level pre-filter — intern dave never sees high-sens docs ──────
SENSITIVE_TITLES = {
    "CEO Compensation Package 2026",
    "Q4 2025 Finance Report",
    "Security Incident Retrospective SI-2026-014",
    "2026 Marketing Strategy",
}


@pytest.mark.parametrize("query", [
    "What is the CEO compensation package?",
    "Tell me about Q4 finance and revenue numbers",
    "Describe the recent security incident retrospective",
    "What is the marketing strategy for 2026?",
])
def test_intern_chroma_prefilter_excludes_sensitive_docs(tokens, query):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["dave"]),
        json={"query": query},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    cited_titles = {c["title"] for c in j["citations"]}
    leak = cited_titles & SENSITIVE_TITLES
    assert not leak, f"Intern saw forbidden docs in citations: {leak}"


# ── SSE streaming endpoint ─────────────────────────────────────────────────────
def _parse_sse(raw_lines):
    """Parse SSE bytes/iter into list of (event, data_dict) tuples."""
    events = []
    cur_event = None
    cur_data = []
    for line in raw_lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if line == "":
            if cur_event is not None:
                data_str = "".join(cur_data)
                try:
                    data = json.loads(data_str) if data_str else {}
                except json.JSONDecodeError:
                    data = {"_raw": data_str}
                events.append((cur_event, data))
            cur_event = None
            cur_data = []
            continue
        if line.startswith("event: "):
            cur_event = line[len("event: "):].strip()
        elif line.startswith("data: "):
            cur_data.append(line[len("data: "):])
    return events


def test_chat_stream_requires_auth():
    r = requests.post(f"{API}/chat/stream", json={"query": "hi"}, timeout=15)
    assert r.status_code == 401


def test_chat_stream_admin_event_sequence(tokens):
    with requests.post(
        f"{API}/chat/stream",
        headers={**H(tokens["alice"]), "Accept": "text/event-stream"},
        json={"query": "What is the engineering roadmap for H1 2026?"},
        timeout=180,
        stream=True,
    ) as r:
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "text/event-stream" in ct, f"unexpected content-type: {ct}"
        events = _parse_sse(r.iter_lines(decode_unicode=True))

    event_types = [e[0] for e in events]
    assert event_types[0] == "meta", f"first event should be meta, got {event_types[:3]}"
    assert event_types.count("meta") == 1
    assert "token" in event_types, f"no token events: {event_types}"
    assert event_types[-1] == "done", f"last event should be done, got {event_types[-3:]}"

    meta = next(d for ev, d in events if ev == "meta")
    for k in ["citations", "access_decision", "guardrail_triggered", "filtered_out_count", "session_id"]:
        assert k in meta, f"meta missing {k}: {meta}"

    tokens_payloads = [d for ev, d in events if ev == "token"]
    assert len(tokens_payloads) >= 1
    assert all("t" in d for d in tokens_payloads)

    done = next(d for ev, d in events if ev == "done")
    assert "answer" in done
    full_from_tokens = "".join(d["t"] for d in tokens_payloads)
    assert done["answer"] == full_from_tokens, "done.answer must equal concatenation of tokens"


def test_chat_stream_intern_ceo_no_leak(tokens):
    leak_strings = ["4.8m", "$4.8", "1.2m", "2.1m", "1.5m"]
    with requests.post(
        f"{API}/chat/stream",
        headers={**H(tokens["dave"]), "Accept": "text/event-stream"},
        json={"query": "What is the CEO compensation package?"},
        timeout=180,
        stream=True,
    ) as r:
        assert r.status_code == 200
        events = _parse_sse(r.iter_lines(decode_unicode=True))

    meta = next(d for ev, d in events if ev == "meta")
    cited_titles = [c["title"] for c in meta["citations"]]
    assert "CEO Compensation Package 2026" not in cited_titles

    token_text = "".join(d["t"] for ev, d in events if ev == "token").lower()
    for leak in leak_strings:
        assert leak not in token_text, f"Intern stream leaked '{leak}'"

    done = next(d for ev, d in events if ev == "done")
    ans_lower = done["answer"].lower()
    assert "unable to find" in ans_lower, f"expected fallback answer, got: {done['answer']}"


# ── Upload→stream→delete reflects in Chroma index live ────────────────────────
def test_chroma_index_live_after_upload_and_delete(tokens):
    payload = {
        "title": "TEST_Quarterly_Manager_Brief",
        "content": (
            "Quarterly manager-only briefing. Topics: budget allocation, headcount planning, "
            "q1 hiring targets, departmental priorities, and OKRs."
        ),
        "role_access": ["manager", "admin"],
        "department": "All",
        "sensitivity": "medium",
    }
    r = requests.post(f"{API}/documents", headers=H(tokens["alice"]), json=payload, timeout=30)
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    try:
        # Manager bob should now retrieve the new doc via Chroma chunk search.
        r2 = requests.post(
            f"{API}/chat",
            headers=H(tokens["bob"]),
            json={"query": "Tell me about the quarterly manager-only briefing on budget and headcount."},
            timeout=120,
        )
        assert r2.status_code == 200
        cited = {c["title"] for c in r2.json()["citations"]}
        assert "TEST_Quarterly_Manager_Brief" in cited, f"Manager did not see new doc; cited={cited}"

        # Intern dave must still NOT see it (role_access excludes intern).
        r3 = requests.post(
            f"{API}/chat",
            headers=H(tokens["dave"]),
            json={"query": "Tell me about the quarterly manager-only briefing on budget and headcount."},
            timeout=120,
        )
        assert r3.status_code == 200
        cited_dave = {c["title"] for c in r3.json()["citations"]}
        assert "TEST_Quarterly_Manager_Brief" not in cited_dave
    finally:
        rd = requests.delete(f"{API}/documents/{doc_id}", headers=H(tokens["alice"]), timeout=15)
        assert rd.status_code == 200

    # After delete, manager bob must no longer see it.
    r4 = requests.post(
        f"{API}/chat",
        headers=H(tokens["bob"]),
        json={"query": "Tell me about the quarterly manager-only briefing on budget and headcount."},
        timeout=120,
    )
    assert r4.status_code == 200
    cited_after = {c["title"] for c in r4.json()["citations"]}
    assert "TEST_Quarterly_Manager_Brief" not in cited_after, "Doc still indexed after delete!"
