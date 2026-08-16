"""One-command build: process everything once the video + API key are in place.

Runs, in order: download papers -> init DB -> ingest video -> ingest documents ->
build search index -> build knowledge graph. Resumable/cached, so re-running is cheap.

    ./.venv/bin/python scripts/build_all.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config

PY = sys.executable


def run(desc: str, script: str):
    print(f"\n\033[1m==> {desc}\033[0m")
    r = subprocess.run([PY, str(ROOT / "scripts" / script)])
    if r.returncode != 0:
        sys.exit(f"\nFAILED at: {desc}. Fix the error above and re-run (it resumes).")


def main():
    # --- preflight checks ---
    if not config.OPENAI_API_KEY:
        sys.exit("ERROR: OPENAI_API_KEY not set. Copy .env.example to .env and add your key.")
    if not config.VIDEO_PATH.exists():
        sys.exit(f"ERROR: no video at {config.VIDEO_PATH}. Add your surgery.mp4 there first.")

    print("Preflight OK: API key present, video found.")
    print(f"Video: {config.VIDEO_PATH}  (~cost: a new video ≈ $0.5–1 on gpt-4o-mini)")

    run("1/5  Downloading guideline PDFs", "download_papers.py")
    run("2/5  Initializing database", "init_db.py")
    run("3/5  Analyzing video -> observations (resumable, ~10-15 min)", "ingest_video.py")
    run("4/5  Ingesting documents -> chunks + embeddings", "ingest_documents.py")
    run("5/5  Building search index", "build_index.py")
    # graph build is its own step (uses the DB + docs)
    print("\n\033[1m==> Building knowledge graph\033[0m")
    if subprocess.run([PY, str(ROOT / "scripts" / "build_graph.py")]).returncode != 0:
        sys.exit("FAILED building graph.")

    print("\n\033[1m✅ Build complete.\033[0m Launch the app with either:")
    print("   ./.venv/bin/python server.py          # web UI  -> http://127.0.0.1:8000")
    print("   ./.venv/bin/streamlit run app.py      # streamlit UI")


if __name__ == "__main__":
    main()
