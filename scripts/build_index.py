"""Phase 2 entrypoint: build the video observation search index from SQLite.

Run after ingestion, and again after any physician review edits (Phase 6).

    ./.venv/bin/python scripts/build_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.index import build_video_index, VIDEO_EMB, VIDEO_META

if __name__ == "__main__":
    n = build_video_index()
    print(f"OK: embedded {n} observations -> {VIDEO_EMB}, {VIDEO_META}")
