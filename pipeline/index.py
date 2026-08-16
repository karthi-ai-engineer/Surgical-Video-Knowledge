"""Phase 2: embed each video observation into a searchable vector index.

Storage is deliberately tiny: a NumPy array of L2-normalized embeddings on disk plus a
parallel JSON of metadata (same order). Cosine similarity is then just a dot product.
Review status is snapshotted into the metadata; rebuild the index after review edits."""
from __future__ import annotations

import json
from typing import List

import numpy as np

import config
from openai import OpenAI
from pipeline.db import get_conn, load_observations
from pipeline.util import fmt_range

VIDEO_EMB = config.DATA_DIR / "video_index.npy"
VIDEO_META = config.DATA_DIR / "video_index.json"
DOC_EMB = config.DATA_DIR / "doc_index.npy"
DOC_META = config.DATA_DIR / "doc_index.json"

EMBED_BATCH = 128  # inputs per embeddings request

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set (put it in .env).")
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def build_search_text(obs: dict) -> str:
    """Human-readable, retrieval-friendly text for one observation (plan §16).
    Prefers physician-edited text when the observation was edited."""
    body = obs["observation"]
    if obs.get("review_status") == "edited" and obs.get("reviewed_text"):
        body = obs["reviewed_text"]
    instruments = ", ".join(obs.get("instruments") or []) or "none noted"
    actions = ", ".join(obs.get("actions") or []) or "none noted"
    return (
        f"Procedure: {config.PROCEDURE}\n"
        f"Timestamp: {fmt_range(obs['start_sec'], obs['end_sec'])}\n"
        f"Phase: {obs['phase']}\n"
        f"Instruments: {instruments}\n"
        f"Actions: {actions}\n"
        f"Observation: {body}"
    )


def embed_texts(texts: List[str]) -> np.ndarray:
    """Return L2-normalized embeddings, shape (len(texts), dim). Batches large inputs."""
    if not texts:
        return np.zeros((0, 1536), dtype=np.float32)
    vecs: List[List[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i + EMBED_BATCH]
        resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=batch)
        vecs.extend(d.embedding for d in resp.data)
    arr = np.array(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # guard against zero vectors
    return arr / norms


def build_video_index() -> int:
    """Read all observations from SQLite, embed, and persist the index. Returns count."""
    with get_conn() as conn:
        rows = load_observations(conn)
    if not rows:
        raise RuntimeError("No observations in DB. Run scripts/ingest_video.py first.")

    for r in rows:
        r["search_text"] = build_search_text(r)
    emb = embed_texts([r["search_text"] for r in rows])

    np.save(VIDEO_EMB, emb)
    VIDEO_META.write_text(json.dumps(rows, indent=2))
    return len(rows)


def build_document_index() -> int:
    """Chunk all PDFs in data/papers/, embed, persist the index, and mirror chunks
    into SQLite. Returns the chunk count."""
    from pipeline.documents import load_all_chunks
    from pipeline.db import replace_document_chunks

    chunks = load_all_chunks()  # List[DocumentChunk]
    meta = [c.model_dump() for c in chunks]
    for m in meta:
        m["search_text"] = m["chunk_text"]
    emb = embed_texts([m["search_text"] for m in meta])

    np.save(DOC_EMB, emb)
    DOC_META.write_text(json.dumps(meta, indent=2))
    replace_document_chunks(chunks)
    return len(meta)


if __name__ == "__main__":
    n = build_video_index()
    print(f"Built video index: {n} observations -> {VIDEO_EMB.name}, {VIDEO_META.name}")
    m = build_document_index()
    print(f"Built document index: {m} chunks -> {DOC_EMB.name}, {DOC_META.name}")
