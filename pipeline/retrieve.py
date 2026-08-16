"""Phase 2: search the video observation index by semantic similarity.

search_video(query) embeds the query and ranks observations by cosine similarity
(a dot product, since stored vectors are L2-normalized)."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import List

import numpy as np

from pipeline import index
from pipeline.index import VIDEO_EMB, VIDEO_META, DOC_EMB, DOC_META


def _load(emb_path, meta_path, what: str):
    if not emb_path.exists() or not meta_path.exists():
        raise RuntimeError(
            f"{what} index not found. Build it: ./.venv/bin/python scripts/build_index.py"
        )
    return np.load(emb_path), json.loads(meta_path.read_text())


@lru_cache(maxsize=1)
def _cached_index():
    return _load(VIDEO_EMB, VIDEO_META, "Video")


@lru_cache(maxsize=1)
def _cached_doc_index():
    return _load(DOC_EMB, DOC_META, "Document")


def refresh():
    """Drop cached indexes (call after rebuilding, e.g. after review edits)."""
    _cached_index.cache_clear()
    _cached_doc_index.cache_clear()


def search_video(query: str, top_k: int = 3, reviewed_only: bool = False) -> List[dict]:
    """Return up to top_k observations most similar to `query`, each with a 'score'.
    If reviewed_only, restrict to approved/edited observations."""
    query = (query or "").strip()
    if not query:
        return []

    emb, meta = _cached_index()

    # Candidate mask (reviewed-only filter for the Phase 6 workflow). Read review state
    # LIVE from the DB so approve/reject takes effect without rebuilding the index.
    idxs = np.arange(len(meta))
    if reviewed_only:
        from pipeline.db import get_reviewed_start_secs
        reviewed = get_reviewed_start_secs()
        idxs = np.array([i for i in idxs if meta[i].get("start_sec") in reviewed])
        if idxs.size == 0:
            return []

    q = index.embed_texts([query])[0]
    sims = emb[idxs] @ q

    k = min(top_k, idxs.size)
    top_local = np.argpartition(-sims, k - 1)[:k]
    top_local = top_local[np.argsort(-sims[top_local])]

    results = []
    for local in top_local:
        m = dict(meta[int(idxs[local])])
        m["score"] = float(sims[local])
        m["source_type"] = "video"
        results.append(m)
    return results


def search_documents(query: str, top_k: int = 3) -> List[dict]:
    """Return up to top_k document chunks most similar to `query`, each with a 'score'."""
    query = (query or "").strip()
    if not query:
        return []

    emb, meta = _cached_doc_index()
    q = index.embed_texts([query])[0]
    sims = emb @ q

    k = min(top_k, len(meta))
    if k == 0:
        return []
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]

    results = []
    for i in top:
        m = dict(meta[int(i)])
        m["score"] = float(sims[int(i)])
        m["source_type"] = "document"
        results.append(m)
    return results


if __name__ == "__main__":
    import sys
    from pipeline.util import fmt_range

    q = " ".join(sys.argv[1:]) or "Where does clipping begin?"
    print(f"Query: {q}\n--- VIDEO ---")
    for r in search_video(q, top_k=3):
        print(f"[{r['score']:.3f}] {fmt_range(r['start_sec'], r['end_sec'])}  {r['phase']}")
        print(f"        {r['observation'][:120]}")
    print("--- DOCUMENTS ---")
    for r in search_documents(q, top_k=3):
        loc = f"{r['document_name']} p{r['page']}"
        print(f"[{r['score']:.3f}] {loc}")
        print(f"        {r['chunk_text'][:120]}")
