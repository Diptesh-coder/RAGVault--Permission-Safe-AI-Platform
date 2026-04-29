"""Vector retrieval powered by ChromaDB with chunk-level RBAC+ABAC metadata filters.

Design:
  * Every document is split into overlapping chunks (see chunking.py).
  * Each chunk is stored in a single Chroma collection with its parent's policy
    metadata (role flags, department, sensitivity_rank).
  * At query time we translate the caller's attributes into a Chroma `where`
    clause so that the vector index itself refuses to surface forbidden chunks.
    This is the "filter-before-retrieve" guarantee at the DB layer.
"""
from typing import List, Tuple, Dict, Optional
import os
import threading
import chromadb

from models import UserPublic
from chunking import build_chunk_records

_CHROMA_PATH = os.path.join(os.path.dirname(__file__), ".chroma")
_COLLECTION = "sentinel_docs"
_SENSITIVITY_RANK = {"low": 1, "medium": 2, "high": 3}
_lock = threading.Lock()

_client = chromadb.PersistentClient(path=_CHROMA_PATH)


def _get_collection():
    return _client.get_or_create_collection(name=_COLLECTION)


# ── Index maintenance ─────────────────────────────────────────────────────────
def rebuild_index(all_docs: List[Dict]) -> int:
    """Wipe the collection and reindex every chunk. Idempotent, called on startup."""
    with _lock:
        try:
            _client.delete_collection(_COLLECTION)
        except Exception:
            pass
        col = _client.get_or_create_collection(name=_COLLECTION)
        total_chunks = 0
        for d in all_docs:
            records = build_chunk_records(d)
            if not records:
                continue
            col.add(
                ids=[r["id"] for r in records],
                documents=[r["document"] for r in records],
                metadatas=[r["metadata"] for r in records],
            )
            total_chunks += len(records)
        return total_chunks


def upsert_document(doc: Dict) -> int:
    with _lock:
        col = _get_collection()
        # Remove any prior chunks for this doc
        try:
            col.delete(where={"doc_id": doc["id"]})
        except Exception:
            pass
        records = build_chunk_records(doc)
        if not records:
            return 0
        col.add(
            ids=[r["id"] for r in records],
            documents=[r["document"] for r in records],
            metadatas=[r["metadata"] for r in records],
        )
        return len(records)


def remove_document(doc_id: str) -> None:
    with _lock:
        col = _get_collection()
        try:
            col.delete(where={"doc_id": doc_id})
        except Exception:
            pass


# ── Retrieval ─────────────────────────────────────────────────────────────────
def _build_where(user: UserPublic) -> Optional[Dict]:
    user_rank = _SENSITIVITY_RANK.get(user.clearance, 1)
    role_flag = f"role_{user.role}"

    clauses: List[Dict] = [
        {role_flag: {"$eq": True}},
        {"sensitivity_rank": {"$lte": user_rank}},
    ]
    # Admins bypass the department check.
    if user.role != "admin":
        clauses.append({
            "$or": [
                {"department": {"$eq": "All"}},
                {"department": {"$eq": user.department}},
            ]
        })
    return {"$and": clauses}


def retrieve(user: UserPublic, query: str, k: int = 4) -> List[Tuple[Dict, float]]:
    """Vector search restricted to chunks the user is authorized to see.

    Returns [(chunk_metadata_with_text, score), ...] deduplicated by doc_id so
    the same document is never cited twice.
    """
    col = _get_collection()
    where = _build_where(user)
    try:
        res = col.query(
            query_texts=[query],
            n_results=max(k * 3, k),  # over-fetch, then dedupe per doc
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    metadatas = (res.get("metadatas") or [[]])[0]
    documents = (res.get("documents") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]

    seen_docs: set = set()
    out: List[Tuple[Dict, float]] = []
    for meta, doc_text, dist in zip(metadatas, documents, distances):
        doc_id = meta.get("doc_id")
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)
        score = max(0.0, 1.0 - float(dist))  # cosine distance → similarity
        chunk = {
            "doc_id": doc_id,
            "title": meta.get("title"),
            "department": meta.get("department"),
            "sensitivity": meta.get("sensitivity"),
            "content": doc_text,
            "chunk_index": meta.get("chunk_index", 0),
        }
        out.append((chunk, score))
        if len(out) >= k:
            break
    return out
