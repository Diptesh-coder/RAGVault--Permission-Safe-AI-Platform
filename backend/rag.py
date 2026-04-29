"""Lightweight RAG retrieval using TF-IDF cosine similarity.

We keep an in-memory index that is rebuilt on demand whenever documents change.
Retrieval is done ONLY over the pre-filtered (RBAC/ABAC-allowed) subset of docs.
"""
from typing import List, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


def retrieve_top_k(
    query: str, allowed_docs: List[dict], k: int = 4
) -> List[Tuple[dict, float]]:
    """Return list of (doc, score) pairs for the top-k matches among allowed docs."""
    if not allowed_docs:
        return []

    corpus = [f"{d['title']}. {d['content']}" for d in allowed_docs]
    vectorizer = TfidfVectorizer(stop_words="english", max_features=4096)
    try:
        doc_matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([query])
    except ValueError:
        # Empty vocabulary (e.g., query is only stopwords)
        return [(d, 0.0) for d in allowed_docs[:k]]

    sims = cosine_similarity(query_vec, doc_matrix)[0]
    order = np.argsort(-sims)[:k]
    results: List[Tuple[dict, float]] = []
    for idx in order:
        score = float(sims[idx])
        if score <= 0:
            continue
        results.append((allowed_docs[int(idx)], score))
    # If no positive match, still return top candidates so the LLM has context
    if not results:
        results = [(allowed_docs[int(i)], float(sims[int(i)])) for i in order[:k]]
    return results
