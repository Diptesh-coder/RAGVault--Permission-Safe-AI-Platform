# SentinelRAG — Policy-Aware RAG with RBAC + ABAC

## Original Problem Statement
Full-stack Permission-Aware AI system using Retrieval-Augmented Generation (RAG) with Role-Based Access Control (RBAC), upgraded to an enterprise-grade Policy-Aware Retrieval System with Fine-Grained Access Control (RBAC + ABAC + Row-Level Security). Secure chatbot answers queries only from documents the user is authorized to access; filter happens BEFORE retrieval so no unauthorized content ever reaches the LLM.

## Architecture
- **Backend**: FastAPI (async) + MongoDB (users, documents, audit_logs) + scikit-learn TF-IDF for retrieval.
- **LLM**: Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) via `emergentintegrations` + Emergent Universal Key.
- **Auth**: JWT-based (bcrypt hashes, HS256). Simulated SSO/LDAP seed directory.
- **Pipeline**: `auth → guardrails → pre-filter (RBAC+ABAC) → retrieve (top-k TF-IDF) → LLM → audit log`.
- **Frontend**: React 19 + react-router-dom, Shadcn/UI, Tailwind, Sonner toasts. Swiss / High-Contrast design with Cabinet Grotesk + IBM Plex.

## Personas
- **Admin** (alice) — Executive dept, clearance high. Sees everything, uploads docs, views audit/users.
- **Manager** (bob) — Finance dept, clearance high. Sees manager-tagged docs in Finance + All.
- **Employee** (carol) — Engineering dept, clearance medium.
- **Intern** (dave) — Engineering dept, clearance low. Sees only the 3 low-sensitivity "All" docs.

## Core Requirements (static)
1. RBAC role check per doc
2. ABAC department + sensitivity clearance check
3. Pre-filter BEFORE retrieval (no leak to LLM)
4. Query guardrails flag sensitive patterns
5. Audit trail of every query (user, role, query, access, cited doc ids, filtered-out count)
6. Admin dashboard (upload, delete, view audit + users)
7. Explainability — citations + access decision visible in UI

## Iteration 2 (2026-02) — production-grade upgrades
- Word-boundary regex guardrails (`\b…\b`) eliminate false positives like `ssn` ⊂ `lessons`
- ChromaDB persistent vector store with overlapping chunking; RBAC+ABAC enforced as a `where` clause at the chunk level (row-level security at the DB layer)
- SSE streaming endpoint `POST /api/chat/stream` (`meta` → `token×N` → `done`); frontend has Streaming/Batch toggle with animated cursor
- Verified by 28/28 backend tests + 10/10 Playwright frontend flows

## Implemented (2026-02)
- Backend modules: `auth.py`, `rbac.py`, `rag.py`, `guardrails.py`, `llm_service.py`, `seed.py`, `models.py`, `server.py`
- REST API: `/api/auth/login`, `/api/auth/me`, `/api/chat`, `/api/documents` (GET/POST), `/api/documents/all`, `/api/documents/{id}` (DELETE), `/api/audit-logs`, `/api/users`
- Seeded: 4 users × 8 documents spanning low/medium/high sensitivity and multiple departments
- Frontend pages: Login (split-screen + 4 one-click demo accounts), Chat (with explainability side panel, guardrail & access-denied banners, inline citations), Documents library (admin upload dialog with role/dept/sensitivity chips), Audit trail (stats + dense table, denied rows tinted red), Users directory
- Header with role chip + logout, admin-only nav tabs hidden for non-admins
- Tested: 17/17 backend tests pass including the critical CEO-salary leak test for intern dave

## Prioritized Backlog
- **P1**: Streaming LLM responses via SSE; multi-turn conversation memory (Redis-backed session store)
- **P1**: Word-boundary regex for guardrail patterns (reduce false positives)
- **P2**: Document chunking for long files (current retrieval is whole-doc)
- **P2**: Clearance-elevation request flow (intern requests temporary read access → admin approves)
- **P2**: ChromaDB / pgvector migration for production-scale corpora
- **P3**: Docker Compose with Postgres + Redis

## Next Tasks (post-first-finish)
- Validate frontend flows via screenshot or Playwright run
- Add streaming if user wants
- Extend audit with CSV export for compliance officers
