"""SentinelRAG backend regression tests — RBAC+ABAC, guardrails, audit logs."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://secure-rag-rbac.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "alice": "admin123",
    "bob":   "manager123",
    "carol": "emp123",
    "dave":  "intern123",
}


@pytest.fixture(scope="session")
def tokens():
    out = {}
    for u, p in CREDS.items():
        r = requests.post(f"{API}/auth/login", json={"username": u, "password": p}, timeout=30)
        assert r.status_code == 200, f"login {u}: {r.status_code} {r.text}"
        out[u] = r.json()["access_token"]
    return out


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── Auth ──────────────────────────────────────────────────────────────────────
def test_login_invalid():
    r = requests.post(f"{API}/auth/login", json={"username": "alice", "password": "wrong"}, timeout=15)
    assert r.status_code == 401


def test_jwt_required_on_protected_endpoints():
    for ep in ["/auth/me", "/documents", "/users", "/audit-logs"]:
        r = requests.get(f"{API}{ep}", timeout=15)
        assert r.status_code == 401, f"{ep} expected 401 got {r.status_code}"


def test_auth_me_returns_user(tokens):
    r = requests.get(f"{API}/auth/me", headers=H(tokens["dave"]), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["username"] == "dave"
    assert j["role"] == "intern"
    assert j["department"] == "Engineering"
    assert j["clearance"] == "low"


# ── Documents listing (RBAC+ABAC) ─────────────────────────────────────────────
def test_admin_sees_all_8_docs(tokens):
    r = requests.get(f"{API}/documents", headers=H(tokens["alice"]), timeout=15)
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 8, f"admin should see 8 docs, got {len(docs)}"


def test_intern_sees_exactly_3_docs(tokens):
    r = requests.get(f"{API}/documents", headers=H(tokens["dave"]), timeout=15)
    assert r.status_code == 200
    titles = sorted(d["title"] for d in r.json())
    expected = sorted(["Company Leave Policy", "Intern Onboarding Handbook", "Code of Conduct"])
    assert titles == expected, f"expected {expected} got {titles}"


def test_employee_sees_engineering_and_all_low(tokens):
    r = requests.get(f"{API}/documents", headers=H(tokens["carol"]), timeout=15)
    assert r.status_code == 200
    titles = {d["title"] for d in r.json()}
    # carol = employee/Engineering/medium
    assert "Engineering Roadmap H1 2026" in titles
    assert "Company Leave Policy" in titles
    assert "Code of Conduct" in titles
    assert "Intern Onboarding Handbook" in titles
    assert "Q4 2025 Finance Report" not in titles
    assert "CEO Compensation Package 2026" not in titles
    assert "Security Incident Retrospective SI-2026-014" not in titles
    assert "2026 Marketing Strategy" not in titles


def test_manager_finance_sees_q4_finance(tokens):
    r = requests.get(f"{API}/documents", headers=H(tokens["bob"]), timeout=15)
    assert r.status_code == 200
    titles = {d["title"] for d in r.json()}
    assert "Q4 2025 Finance Report" in titles


# ── Chat: CORE RBAC test (CEO salary) ─────────────────────────────────────────
def test_intern_ceo_salary_blocked(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["dave"]),
        json={"query": "What is the CEO salary?"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    # Guardrail must trigger
    assert j["guardrail_triggered"] is True
    assert j["guardrail_reason"]
    # No citation should reference CEO comp doc
    cited_titles = [c["title"] for c in j["citations"]]
    assert "CEO Compensation Package 2026" not in cited_titles
    # Answer must NOT leak salary numbers
    ans = j["answer"].lower()
    for leak in ["4.8m", "$4.8", "1.2m", "2.1m", "1.5m", "performance bonus"]:
        assert leak not in ans, f"intern answer leaked '{leak}': {j['answer']}"
    # filtered_out should be > 0 (some docs filtered)
    assert j["filtered_out_count"] >= 1


def test_admin_ceo_salary_granted(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["alice"]),
        json={"query": "What is the CEO salary?"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    cited_titles = [c["title"] for c in j["citations"]]
    assert "CEO Compensation Package 2026" in cited_titles
    # Top citation for CEO doc must have positive score
    ceo_cite = next(c for c in j["citations"] if c["title"] == "CEO Compensation Package 2026")
    assert ceo_cite["score"] > 0
    # Answer should reference compensation figures
    ans = j["answer"]
    assert "4.8" in ans or "$4.8" in ans or "4.8M" in ans.upper()


def test_guardrail_flags_ceo_salary(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["alice"]),
        json={"query": "What is CEO salary?"},
        timeout=120,
    )
    assert r.status_code == 200
    j = r.json()
    assert j["guardrail_triggered"] is True
    assert "ceo salary" in (j["guardrail_reason"] or "").lower()


def test_employee_q4_finance_excluded(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["carol"]),
        json={"query": "Tell me about the Q4 2025 finance report and revenue."},
        timeout=120,
    )
    assert r.status_code == 200
    j = r.json()
    cited_titles = [c["title"] for c in j["citations"]]
    assert "Q4 2025 Finance Report" not in cited_titles


def test_manager_q4_finance_included(tokens):
    r = requests.post(
        f"{API}/chat",
        headers=H(tokens["bob"]),
        json={"query": "Tell me about the Q4 2025 finance report and revenue."},
        timeout=120,
    )
    assert r.status_code == 200
    j = r.json()
    cited_titles = [c["title"] for c in j["citations"]]
    assert "Q4 2025 Finance Report" in cited_titles


# ── Document upload / delete ──────────────────────────────────────────────────
def test_intern_cannot_upload_doc(tokens):
    r = requests.post(
        f"{API}/documents",
        headers=H(tokens["dave"]),
        json={
            "title": "TEST_intern_upload",
            "content": "should fail",
            "role_access": ["intern"],
            "department": "All",
            "sensitivity": "low",
        },
        timeout=15,
    )
    assert r.status_code == 403


def test_admin_can_upload_and_delete(tokens):
    payload = {
        "title": "TEST_admin_upload_doc",
        "content": "Temporary doc for testing.",
        "role_access": ["admin"],
        "department": "Executive",
        "sensitivity": "low",
    }
    r = requests.post(f"{API}/documents", headers=H(tokens["alice"]), json=payload, timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["title"] == payload["title"]
    doc_id = doc["id"]

    # verify GET sees it
    r2 = requests.get(f"{API}/documents", headers=H(tokens["alice"]), timeout=15)
    assert any(d["id"] == doc_id for d in r2.json())

    # delete
    r3 = requests.delete(f"{API}/documents/{doc_id}", headers=H(tokens["alice"]), timeout=15)
    assert r3.status_code == 200
    assert r3.json()["deleted"] == doc_id

    # confirm removed
    r4 = requests.get(f"{API}/documents", headers=H(tokens["alice"]), timeout=15)
    assert not any(d["id"] == doc_id for d in r4.json())


def test_intern_cannot_delete(tokens):
    r = requests.delete(f"{API}/documents/some-id", headers=H(tokens["dave"]), timeout=15)
    assert r.status_code == 403


# ── Admin endpoints ───────────────────────────────────────────────────────────
def test_audit_logs_admin_only(tokens):
    r1 = requests.get(f"{API}/audit-logs", headers=H(tokens["dave"]), timeout=15)
    assert r1.status_code == 403

    r2 = requests.get(f"{API}/audit-logs", headers=H(tokens["alice"]), timeout=15)
    assert r2.status_code == 200
    logs = r2.json()
    assert isinstance(logs, list)
    assert len(logs) >= 1
    log0 = logs[0]
    for k in ["username", "role", "query", "access", "guardrail_triggered",
              "cited_doc_ids", "filtered_out_count", "timestamp"]:
        assert k in log0, f"missing field {k}"
    # sorted desc
    ts = [l["timestamp"] for l in logs]
    assert ts == sorted(ts, reverse=True)


def test_users_admin_only(tokens):
    r1 = requests.get(f"{API}/users", headers=H(tokens["carol"]), timeout=15)
    assert r1.status_code == 403

    r2 = requests.get(f"{API}/users", headers=H(tokens["alice"]), timeout=15)
    assert r2.status_code == 200
    users = r2.json()
    usernames = sorted(u["username"] for u in users)
    assert usernames == sorted(["alice", "bob", "carol", "dave"])
