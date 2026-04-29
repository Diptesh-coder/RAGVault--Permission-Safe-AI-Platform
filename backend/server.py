"""SentinelRAG — Policy-Aware RAG backend (FastAPI).

Pipeline:
    auth (JWT) → guardrails → Chroma vector search pre-filtered by RBAC+ABAC → LLM → audit log
"""
import os
import json
import uuid
import hmac
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from models import (
    LoginRequest, LoginResponse, UserPublic,
    DocumentCreate, DocumentPublic, Document,
    ChatRequest, ChatResponse, Citation, AuditLog,
)
from auth import (
    verify_password, create_access_token, decode_token, bearer_scheme, require_admin,
)
import rbac
import rag
import guardrails
import llm_service
import seed as seed_module
import metrics

# ── DB ─────────────────────────────────────────────────────────────────────────
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="SentinelRAG")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sentinel_rag")


# ── Startup ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup():
    await seed_module.seed_database(db)
    # Rebuild Chroma vector index from the current Mongo corpus.
    all_docs = await db.documents.find({}, {"_id": 0}).to_list(10_000)
    count = rag.rebuild_index(all_docs)
    # Warm the ONNX embedding model so the first user query is fast.
    try:
        rag.warmup()
        logger.info(f"SentinelRAG startup — {len(all_docs)} docs, {count} chunks indexed; embedder warm.")
    except Exception as e:
        logger.warning(f"Embedder warmup failed (non-fatal): {e}")


@app.on_event("shutdown")
async def _shutdown():
    client.close()


# ── Auth dependency ────────────────────────────────────────────────────────────
async def _current_user(creds=Depends(bearer_scheme)) -> UserPublic:
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    username = payload.get("sub")
    user_doc = await db.users.find_one({"username": username}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return UserPublic(**{k: user_doc[k] for k in UserPublic.model_fields.keys()})


async def _user_from_token_string(token: str) -> UserPublic:
    payload = decode_token(token)
    user_doc = await db.users.find_one({"username": payload.get("sub")}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return UserPublic(**{k: user_doc[k] for k in UserPublic.model_fields.keys()})


# ── Helpers ────────────────────────────────────────────────────────────────────
async def _load_all_documents() -> List[dict]:
    return await db.documents.find({}, {"_id": 0}).to_list(10_000)


def _to_public_doc(doc: dict) -> DocumentPublic:
    d = dict(doc)
    if isinstance(d.get("uploaded_at"), str):
        d["uploaded_at"] = datetime.fromisoformat(d["uploaded_at"])
    return DocumentPublic(**d)


async def _run_chat_core(user: UserPublic, query: str, session_id: str):
    """Shared RBAC+retrieval pipeline used by both /chat and /chat/stream."""
    triggered, reason = guardrails.check_query(query)

    # Count how many docs the user is excluded from (for UX / audit).
    all_docs = await _load_all_documents()
    _, filtered_out = rbac.filter_documents(user, all_docs)

    # Vector retrieval is already restricted by Chroma's where clause.
    results = rag.retrieve(user, query, k=4)
    context_docs = [chunk for chunk, _ in results]
    citations = [
        Citation(
            doc_id=c["doc_id"], title=c["title"],
            department=c["department"], sensitivity=c["sensitivity"],
            score=round(s, 4),
        )
        for c, s in results
    ]

    if not context_docs and filtered_out > 0:
        decision = "denied"
    elif filtered_out > 0:
        decision = "partial"
    else:
        decision = "granted"

    return {
        "triggered": triggered, "reason": reason,
        "context_docs": context_docs, "citations": citations,
        "decision": decision, "filtered_out": filtered_out,
        "session_id": session_id,
    }


async def _write_audit(user: UserPublic, query: str, state: dict, answer: str | None):
    log = AuditLog(
        username=user.username, role=user.role, department=user.department,
        query=query, access=state["decision"], guardrail_triggered=state["triggered"],
        cited_doc_ids=[c.doc_id for c in state["citations"]],
        filtered_out_count=state["filtered_out"],
    )
    payload = log.model_dump()
    payload["timestamp"] = payload["timestamp"].isoformat()
    await db.audit_logs.insert_one(payload)
    metrics.chat_decision_total.labels(decision=state["decision"]).inc()
    if state["triggered"]:
        metrics.guardrail_triggered_total.inc()


# ── Routes ─────────────────────────────────────────────────────────────────────
@api_router.get("/")
async def root():
    return {"service": "SentinelRAG", "status": "ok"}


@api_router.get("/metrics")
async def prom_metrics(request: Request):
    """Prometheus exposition endpoint.

    If `METRICS_TOKEN` is set in the environment, the caller must present a
    matching `X-Metrics-Token` header. If unset, the endpoint is open (default
    for local dev; in production set the env var via your secret manager and
    configure your Prometheus scrape config to send the header).
    """
    expected = os.environ.get("METRICS_TOKEN")
    if expected:
        provided = request.headers.get("X-Metrics-Token") or ""
        # Constant-time comparison defeats timing side-channels.
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="metrics: invalid or missing token")
    body, content_type = metrics.render_metrics()
    return Response(content=body, media_type=content_type)


@api_router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    user_doc = await db.users.find_one({"username": body.username}, {"_id": 0})
    if not user_doc or not verify_password(body.password, user_doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({"sub": user_doc["username"], "role": user_doc["role"]})
    public = UserPublic(**{k: user_doc[k] for k in UserPublic.model_fields.keys()})
    return LoginResponse(access_token=token, user=public)


@api_router.get("/auth/me", response_model=UserPublic)
async def me(user: UserPublic = Depends(_current_user)):
    return user


# ── Documents ──────────────────────────────────────────────────────────────────
@api_router.get("/documents", response_model=List[DocumentPublic])
async def list_documents(user: UserPublic = Depends(_current_user)):
    docs = await _load_all_documents()
    allowed, _ = rbac.filter_documents(user, docs)
    return [_to_public_doc(d) for d in allowed]


@api_router.get("/documents/all", response_model=List[DocumentPublic])
async def list_all_documents(user: UserPublic = Depends(_current_user)):
    require_admin(user)
    return [_to_public_doc(d) for d in await _load_all_documents()]


@api_router.post("/documents", response_model=DocumentPublic)
async def create_document(body: DocumentCreate, user: UserPublic = Depends(_current_user)):
    require_admin(user)
    doc = Document(**body.model_dump(), uploaded_by=user.username)
    payload = doc.model_dump()
    payload["uploaded_at"] = payload["uploaded_at"].isoformat()
    await db.documents.insert_one(payload)
    # Index chunks in Chroma
    rag.upsert_document(payload)
    return _to_public_doc(payload)


@api_router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, user: UserPublic = Depends(_current_user)):
    require_admin(user)
    res = await db.documents.delete_one({"id": doc_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    rag.remove_document(doc_id)
    return {"deleted": doc_id}


# ── Chat (non-streaming, kept for parity) ──────────────────────────────────────
@api_router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: UserPublic = Depends(_current_user)):
    session_id = body.session_id or str(uuid.uuid4())
    state = await _run_chat_core(user, body.query, session_id)
    try:
        answer = await llm_service.generate_answer(body.query, state["context_docs"], session_id)
    except Exception as e:
        logger.exception("LLM call failed")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    await _write_audit(user, body.query, state, answer)
    return ChatResponse(
        answer=answer, citations=state["citations"], access_decision=state["decision"],
        guardrail_triggered=state["triggered"], guardrail_reason=state["reason"] or None,
        filtered_out_count=state["filtered_out"], session_id=session_id,
    )


# ── Chat (streaming via Server-Sent Events) ────────────────────────────────────
@api_router.post("/chat/stream")
async def chat_stream(body: ChatRequest, user: UserPublic = Depends(_current_user)):
    """SSE streaming chat.

    Emits three kinds of events:
      event: meta    → initial access decision + citations + guardrail info
      event: token   → incremental text fragments of the answer
      event: done    → final signal with the full answer string
    """
    session_id = body.session_id or str(uuid.uuid4())
    state = await _run_chat_core(user, body.query, session_id)

    async def event_stream():
        meta = {
            "session_id": session_id,
            "access_decision": state["decision"],
            "guardrail_triggered": state["triggered"],
            "guardrail_reason": state["reason"] or None,
            "filtered_out_count": state["filtered_out"],
            "citations": [c.model_dump() for c in state["citations"]],
        }
        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"

        buffer: list[str] = []
        try:
            async for tok in llm_service.stream_answer(body.query, state["context_docs"], session_id):
                buffer.append(tok)
                yield f"event: token\ndata: {json.dumps({'t': tok})}\n\n"
        except Exception as e:
            logger.exception("LLM stream failed")
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"
            return

        answer = "".join(buffer)
        await _write_audit(user, body.query, state, answer)
        yield f"event: done\ndata: {json.dumps({'answer': answer})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Audit Logs / Users ─────────────────────────────────────────────────────────
@api_router.get("/audit-logs", response_model=List[AuditLog])
async def audit_logs(user: UserPublic = Depends(_current_user), limit: int = 200):
    require_admin(user)
    rows = await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    for r in rows:
        if isinstance(r.get("timestamp"), str):
            r["timestamp"] = datetime.fromisoformat(r["timestamp"])
    return [AuditLog(**r) for r in rows]


@api_router.get("/users", response_model=List[UserPublic])
async def list_users(user: UserPublic = Depends(_current_user)):
    require_admin(user)
    rows = await db.users.find({}, {"_id": 0}).to_list(1000)
    return [UserPublic(**{k: r[k] for k in UserPublic.model_fields.keys()}) for r in rows]


# ── Wire-up ────────────────────────────────────────────────────────────────────
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
