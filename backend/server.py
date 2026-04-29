"""SentinelRAG — Policy-Aware RAG backend (FastAPI).

Pipeline:
    auth (JWT) → guardrails → pre-filter (RBAC+ABAC) → retrieve (TF-IDF) → LLM → audit log
"""
import os
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
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
    verify_password, create_access_token, get_current_user_factory, require_admin,
)
import rbac
import rag
import guardrails
import llm_service
import seed as seed_module

# ── DB ─────────────────────────────────────────────────────────────────────────
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="SentinelRAG")
api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sentinel_rag")

get_current_user = None  # bound on startup


# ── Startup ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup():
    global get_current_user
    get_current_user = await get_current_user_factory(db)
    await seed_module.seed_database(db)
    logger.info("SentinelRAG startup complete — seed verified.")


@app.on_event("shutdown")
async def _shutdown():
    client.close()


# ── Helpers ────────────────────────────────────────────────────────────────────
async def _load_all_documents() -> List[dict]:
    return await db.documents.find({}, {"_id": 0}).to_list(10_000)


def _to_public_doc(doc: dict) -> DocumentPublic:
    d = dict(doc)
    if isinstance(d.get("uploaded_at"), str):
        d["uploaded_at"] = datetime.fromisoformat(d["uploaded_at"])
    return DocumentPublic(**d)


def _user_dep():
    async def _inner(creds: HTTPAuthorizationCredentials = Depends(__import__("auth").bearer_scheme)):
        return await get_current_user(credentials=creds)
    return _inner


async def _current_user(creds=Depends(__import__("auth").bearer_scheme)) -> UserPublic:
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from auth import decode_token
    payload = decode_token(creds.credentials)
    username = payload.get("sub")
    user_doc = await db.users.find_one({"username": username}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return UserPublic(**{k: user_doc[k] for k in UserPublic.model_fields.keys()})


# ── Routes ─────────────────────────────────────────────────────────────────────
@api_router.get("/")
async def root():
    return {"service": "SentinelRAG", "status": "ok"}


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
    """Returns only documents the caller is authorized to see."""
    docs = await _load_all_documents()
    allowed, _ = rbac.filter_documents(user, docs)
    return [_to_public_doc(d) for d in allowed]


@api_router.get("/documents/all", response_model=List[DocumentPublic])
async def list_all_documents(user: UserPublic = Depends(_current_user)):
    """Admin-only: list every document regardless of access."""
    require_admin(user)
    docs = await _load_all_documents()
    return [_to_public_doc(d) for d in docs]


@api_router.post("/documents", response_model=DocumentPublic)
async def create_document(body: DocumentCreate, user: UserPublic = Depends(_current_user)):
    require_admin(user)
    doc = Document(**body.model_dump(), uploaded_by=user.username)
    payload = doc.model_dump()
    payload["uploaded_at"] = payload["uploaded_at"].isoformat()
    await db.documents.insert_one(payload)
    return _to_public_doc(payload)


@api_router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, user: UserPublic = Depends(_current_user)):
    require_admin(user)
    res = await db.documents.delete_one({"id": doc_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": doc_id}


# ── Chat ───────────────────────────────────────────────────────────────────────
@api_router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: UserPublic = Depends(_current_user)):
    session_id = body.session_id or str(uuid.uuid4())

    # 1. Guardrails (advisory – do not block)
    triggered, reason = guardrails.check_query(body.query)

    # 2. Pre-filter (RBAC + ABAC) BEFORE retrieval
    all_docs = await _load_all_documents()
    allowed, filtered_out = rbac.filter_documents(user, all_docs)

    # 3. Retrieve top-k relevant docs from the allowed subset only
    top = rag.retrieve_top_k(body.query, allowed, k=4)
    context_docs = [d for d, _ in top]
    citations = [
        Citation(
            doc_id=d["id"], title=d["title"], department=d["department"],
            sensitivity=d["sensitivity"], score=round(s, 4),
        )
        for d, s in top
    ]

    # 4. LLM answer (context is exclusively authorized material)
    try:
        answer = await llm_service.generate_answer(body.query, context_docs, session_id)
    except Exception as e:  # surface a polite error without leaking internals
        logger.exception("LLM call failed")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    # 5. Decide access outcome
    if not context_docs and filtered_out > 0:
        decision = "denied"
    elif filtered_out > 0:
        decision = "partial"
    else:
        decision = "granted"

    # 6. Audit log
    log = AuditLog(
        username=user.username, role=user.role, department=user.department,
        query=body.query, access=decision, guardrail_triggered=triggered,
        cited_doc_ids=[c.doc_id for c in citations], filtered_out_count=filtered_out,
    )
    log_payload = log.model_dump()
    log_payload["timestamp"] = log_payload["timestamp"].isoformat()
    await db.audit_logs.insert_one(log_payload)

    return ChatResponse(
        answer=answer, citations=citations, access_decision=decision,
        guardrail_triggered=triggered, guardrail_reason=reason or None,
        filtered_out_count=filtered_out, session_id=session_id,
    )


# ── Audit Logs ─────────────────────────────────────────────────────────────────
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
)
