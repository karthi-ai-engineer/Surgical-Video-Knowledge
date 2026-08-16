"""Phase 3: turn the trusted PDFs in data/papers/ into retrievable text chunks.

Word-aware sliding-window chunking with overlap, keeping the source document name and
page number so every chunk can cite its origin (plan §18)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from pypdf import PdfReader

import config
from models.schemas import DocumentChunk


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_text(text: str, size: int, overlap: int) -> List[str]:
    """Split into ~size-char chunks on word boundaries, with ~overlap chars carried over."""
    words = text.split()
    if not words:
        return []
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for w in words:
        cur.append(w)
        cur_len += len(w) + 1
        if cur_len >= size:
            chunks.append(" ".join(cur))
            keep: List[str] = []
            kl = 0
            for ww in reversed(cur):
                kl += len(ww) + 1
                keep.insert(0, ww)
                if kl >= overlap:
                    break
            cur, cur_len = keep, sum(len(x) + 1 for x in keep)
    if cur:
        tail = " ".join(cur)
        # avoid emitting a tiny trailing fragment that's just the overlap of the last chunk
        if not chunks or tail not in chunks[-1]:
            chunks.append(tail)
    return chunks


def load_pdf_chunks(path: Path) -> List[DocumentChunk]:
    reader = PdfReader(str(path))
    name = path.name
    out: List[DocumentChunk] = []
    for pageno, page in enumerate(reader.pages, start=1):
        text = _clean(page.extract_text() or "")
        if len(text) < 30:  # skip near-empty / figure-only pages
            continue
        for piece in split_text(text, config.DOC_CHUNK_CHARS, config.DOC_CHUNK_OVERLAP):
            if len(piece.strip()) < 30:
                continue
            out.append(DocumentChunk(
                document_name=name, page=pageno, section=None, chunk_text=piece.strip(),
            ))
    return out


def load_all_chunks() -> List[DocumentChunk]:
    """Chunk every PDF in data/papers/, sorted by filename for determinism."""
    pdfs = sorted(config.PAPERS_DIR.glob("*.pdf"))
    if not pdfs:
        raise RuntimeError(f"No PDFs found in {config.PAPERS_DIR}. Add guideline PDFs first.")
    chunks: List[DocumentChunk] = []
    for pdf in pdfs:
        chunks.extend(load_pdf_chunks(pdf))
    return chunks
