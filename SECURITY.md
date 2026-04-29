# SentinelRAG · Security Posture

> Policy-Aware Retrieval-Augmented Generation with **filter-before-retrieve**
> guarantees, fine-grained RBAC + ABAC enforcement, and an end-to-end
> Prometheus + smoke-test observability stack.

---

## 1 · Filter-Before-Retrieve Pipeline

The single most important property of SentinelRAG is that **no unauthorized
document content ever reaches the LLM**. Access control runs **before** vector
similarity search, not after.

```
                         ┌──────────────────────────────────────────────────────┐
                         │                  REQUEST LIFECYCLE                  │
                         └──────────────────────────────────────────────────────┘

   client ──► JWT auth ──► guardrails ──► RBAC + ABAC pre-filter ──► Chroma ──► LLM ──► audit
                │              │                  │                    │         │       │
              401 if         flag        Chroma `where` clause      top-k    Claude   immutable
            no/expired    sensitive       restricts the index      chunks   Sonnet     log row
              token          patterns     to authorized chunks     only      4.5
                                          (chunk-level RLS)
```

### Enforcement layers

| Layer            | What it checks                                                    | File                        |
|------------------|--------------------------------------------------------------------|-----------------------------|
| JWT auth         | Bearer token signature + expiry                                   | `backend/auth.py`           |
| Query guardrails | Word-boundary regex on a sensitive-pattern allowlist              | `backend/guardrails.py`     |
| RBAC pre-filter  | `user.role ∈ doc.role_access`                                     | `backend/rbac.py`           |
| ABAC department  | `doc.department == "All"` or `== user.department` (admin bypass)  | `backend/rbac.py`           |
| ABAC clearance   | `rank(doc.sensitivity) ≤ rank(user.clearance)`                    | `backend/rbac.py`           |
| Vector index     | All three checks compiled into a Chroma `$and` `where` clause     | `backend/rag.py`            |
| LLM prompt       | System message refuses any answer not derived from `<authorized_context>` | `backend/llm_service.py` |
| Audit log        | One row per request: user, query, decision, cited doc IDs, count excluded | `backend/server.py`     |

A **chunk** is the unit of access control: every chunk inherits its parent
document's role flags, department, and sensitivity rank, so a single doc
cannot accidentally leak via partial retrieval.

---

## 2 · Metric Series and Alert Thresholds

`GET /api/metrics` exposes the standard Prometheus exposition format. Five
series cover the security and reliability surface.

| Metric                                       | Type      | Labels        | What to alert on                                                                                  |
|----------------------------------------------|-----------|---------------|---------------------------------------------------------------------------------------------------|
| `sentinel_stream_total`                      | Counter   | —             | `rate(.[5m]) == 0` for >15m during business hours → app likely down                              |
| `sentinel_stream_fallback_total`             | Counter   | —             | **Any** non-zero `rate(.[5m])` → real-stream path is degraded; emergent proxy regression          |
| `sentinel_stream_first_token_seconds`        | Histogram | `path`        | `histogram_quantile(0.95, …{path="real"}) > 8s` for >10m → LLM slow                              |
| `sentinel_chat_decision_total`               | Counter   | `decision`    | `rate(…{decision="denied"}[5m]) / rate(…[5m]) > 0.4` for >30m → spike in unauthorized queries     |
| `sentinel_guardrail_triggered_total`         | Counter   | —             | `rate(.[1h]) > 20` → potential probing / social-engineering attempt; raise to security oncall    |

Cardinality is **bounded by design**: the only labelled series carry an
enumerated label set (`path ∈ {real, fallback}`, `decision ∈ {granted,
partial, denied}`), and `metrics.observe_first_token()` raises `ValueError`
if a developer tries to invent a new path label.

---

## 3 · `METRICS_TOKEN` Rotation Policy

`/api/metrics` is gated by a shared-secret header `X-Metrics-Token` whenever
the backend env var `METRICS_TOKEN` is set. Comparison is constant-time
(`hmac.compare_digest`).

### Lifecycle

| Action               | Cadence       | Operator                                                                                              |
|----------------------|---------------|-------------------------------------------------------------------------------------------------------|
| Generate             | At deploy     | `python3 -c "import secrets; print('ops-' + secrets.token_urlsafe(24))"`                              |
| Distribute           | At deploy     | Inject via secret manager into both backend `.env` (`METRICS_TOKEN`) and Prometheus scrape config     |
| Rotate (routine)     | Every 90 days | New token → secret manager → blue/green redeploy backend → update Prometheus scrape → revoke old      |
| Rotate (emergency)   | Within 1h     | Same flow under incident response; verify scrape target stays green via `up{job="sentinelrag"} == 1`  |
| Revoke               | Per leak      | Update `METRICS_TOKEN` env, restart backend; previous token rejected immediately (constant-time)      |

If `METRICS_TOKEN` is **unset** the endpoint is open — fine for local dev,
not for production. Document this in your deploy checklist.

---

## 4 · Smoke-Test Cron

`backend/scripts/smoke_stream.py` is a stdlib-only script that exits non-zero
if the first SSE chunk does not arrive within `SENTINEL_MAX_FIRST_TOKEN`
seconds (default 6) or if `sentinel_stream_fallback_total` increments during
the run (silent regression to pseudo-stream).

### Crontab snippet

```cron
# Run every 5 minutes; fail loud via system mail and capture stdout
*/5 * * * *  SENTINEL_BASE_URL=https://sentinel.example.com \
             SENTINEL_USER=alice \
             SENTINEL_PASS="${SENTINEL_PASS}" \
             SENTINEL_METRICS_TOKEN="${METRICS_TOKEN}" \
             /usr/bin/python3 /opt/sentinelrag/backend/scripts/smoke_stream.py \
             >> /var/log/sentinelrag/smoke.log 2>&1 || \
             /usr/local/bin/sentinel-pager "smoke_stream FAILED at $(date -u +%FT%TZ)"
```

### Operator checklist when a smoke fails

1. Tail `/var/log/sentinelrag/smoke.log` — was the failure `first token took …s` or `stream_fallback_total incremented`?
2. If `fallback`: check `sentinel_stream_fallback_total` rate, then inspect backend `WARNING` logs for `True streaming failed, falling back…`. Most likely cause: Emergent proxy upstream change.
3. If `first token >6s`: check histogram `sentinel_stream_first_token_seconds{path="real"}` p95 trend — usually an upstream LLM latency event.
4. If smoke can't authenticate: rotate `SENTINEL_PASS` and confirm `METRICS_TOKEN` matches both sides.

---

## 5 · Test Coverage

**80/80 cumulative backend tests** across 6 iterations exercise:

- 4-role JWT login + 401 enforcement on every endpoint
- RBAC + ABAC pre-filter at row and chunk level (intern dave has access to exactly 3 of 8 docs)
- Critical leak test: intern asking "What is the CEO salary?" never receives the salary numbers (`4.8M / 1.2M / 2.1M / 1.5M / "performance bonus"`)
- Word-boundary guardrails (`ssn` ⊂ `lessons` does not trigger; standalone `SSN` does)
- SSE event sequence (`meta → token×N → done`) with real-stream TTFT measured against budgets
- Metric counter increments per request type and per decision label
- Cardinality lock: `observe_first_token('hacked', …)` raises `ValueError`
- `/api/metrics` token wall: 401 / 401 / 200 for missing / wrong / correct header

Run them:

```bash
cd /app/backend && pytest tests/ -v
```

---

*Last updated: iteration 7 — see `/app/memory/PRD.md` for full change log.*
