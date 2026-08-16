"""Phase 3 entrypoint: chunk + embed the trusted PDFs in data/papers/.

    ./.venv/bin/python scripts/ingest_documents.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.documents import load_all_chunks
from pipeline.index import build_document_index, DOC_EMB, DOC_META

if __name__ == "__main__":
    # Quick per-document chunk report first (cheap, no API).
    from collections import Counter
    chunks = load_all_chunks()
    by_doc = Counter(c.document_name for c in chunks)
    print(f"Found {len(by_doc)} PDFs in {config.PAPERS_DIR}:")
    for name, n in sorted(by_doc.items()):
        print(f"  {n:>3} chunks  {name}")
    print(f"\nEmbedding {len(chunks)} chunks...")
    n = build_document_index()
    print(f"OK: embedded {n} chunks -> {DOC_EMB}, {DOC_META} (+ SQLite document_chunks)")
