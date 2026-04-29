"""Simple character-based chunker with overlap for long documents.

Good enough for production-scale retrieval: chunks have overlap to preserve
context across boundaries, and every chunk carries the parent document's
policy metadata so access control is enforced at the chunk level.
"""
from typing import List, Dict

DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 100


def chunk_text(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> List[str]:
    if not text:
        return [""]
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    start = 0
    step = max(1, size - overlap)
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


def build_chunk_records(doc: Dict) -> List[Dict]:
    """Return [{id, document, metadata}] records ready to be added to Chroma."""
    pieces = chunk_text(doc["content"])
    records = []
    for i, piece in enumerate(pieces):
        records.append({
            "id": f"{doc['id']}::chunk-{i}",
            "document": f"{doc['title']}. {piece}",
            "metadata": {
                "doc_id": doc["id"],
                "chunk_index": i,
                "title": doc["title"],
                "department": doc["department"],
                "sensitivity": doc["sensitivity"],
                "sensitivity_rank": {"low": 1, "medium": 2, "high": 3}.get(doc["sensitivity"], 1),
                "uploaded_by": doc.get("uploaded_by", "system"),
                "role_admin": "admin" in doc["role_access"],
                "role_manager": "manager" in doc["role_access"],
                "role_employee": "employee" in doc["role_access"],
                "role_intern": "intern" in doc["role_access"],
            },
        })
    return records
