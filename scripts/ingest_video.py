"""Phase 1 entrypoint: surgery.mp4 -> data/observations.json (+ SQLite).

Resumable and cached: every window's result is saved immediately; re-running skips
already-processed windows. Run a short segment first to check quality and cost:

    ./.venv/bin/python scripts/ingest_video.py --start 0 --end 120     # first 2 min
    ./.venv/bin/python scripts/ingest_video.py                          # whole video
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline import video, analyze
from pipeline.db import get_conn, init_db
from pipeline.util import fmt_range


def load_cache() -> dict:
    """observations.json -> {start_sec: obs_dict}."""
    if config.OBSERVATIONS_JSON.exists():
        data = json.loads(config.OBSERVATIONS_JSON.read_text())
        return {o["start_sec"]: o for o in data}
    return {}


def save_cache(cache: dict) -> None:
    ordered = [cache[k] for k in sorted(cache)]
    config.OBSERVATIONS_JSON.write_text(json.dumps(ordered, indent=2))


def make_windows(frames: list[int], size: int) -> list[list[int]]:
    return [frames[i:i + size] for i in range(0, len(frames), size)]


def sync_to_db(cache: dict) -> int:
    """Insert observations not already in the DB (matched by start_sec). Returns inserted count."""
    from pipeline.db import insert_observation
    from models.schemas import VideoObservation
    init_db()
    inserted = 0
    with get_conn() as conn:
        existing = {r["start_sec"] for r in conn.execute(
            "SELECT start_sec FROM video_observations").fetchall()}
        for start in sorted(cache):
            if start in existing:
                continue
            insert_observation(conn, VideoObservation(**cache[start]))
            inserted += 1
        conn.commit()
    return inserted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0, help="start second")
    ap.add_argument("--end", type=int, default=None, help="end second (default: full video)")
    ap.add_argument("--limit", type=int, default=None, help="max windows to process this run")
    args = ap.parse_args()

    if not config.VIDEO_PATH.exists():
        sys.exit(f"ERROR: video not found at {config.VIDEO_PATH}. Put your file there first.")

    info = video.probe_video(config.VIDEO_PATH)
    print(f"Video: {info.width}x{info.height}, {info.fps:.1f} fps, "
          f"{info.duration_sec:.0f}s (~{info.duration_sec/60:.1f} min)")
    print(f"Sampling: 1 frame / {config.COARSE_INTERVAL_SEC}s, "
          f"batch {config.BATCH_SIZE} -> {config.BATCH_SIZE*config.COARSE_INTERVAL_SEC}s windows")

    print("Extracting frames (resumable)...")
    frames = video.extract_frames(
        start_sec=args.start, end_sec=args.end,
        interval_sec=config.COARSE_INTERVAL_SEC, width=config.FRAME_WIDTH,
    )
    windows = make_windows(frames, config.BATCH_SIZE)
    print(f"{len(frames)} frames -> {len(windows)} windows")

    cache = load_cache()
    todo = [w for w in windows if w and w[0] not in cache]
    already = len([w for w in windows if w and w[0] in cache])
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(windows)} windows total: {already} already cached, "
          f"{len(todo)} to analyze this run")

    for i, w in enumerate(todo, 1):
        obs = analyze.analyze_window(w)
        cache[w[0]] = obs.model_dump()
        save_cache(cache)  # save after every window -> crash-safe / resumable
        flag = "★" if obs.important else " "
        print(f"[{i}/{len(todo)}] {flag} {fmt_range(obs.start_sec, obs.end_sec)}  "
              f"{obs.phase:<26} conf={obs.confidence:.2f}")

    inserted = sync_to_db(cache)
    print(f"\nDone. observations.json has {len(cache)} windows; "
          f"inserted {inserted} new rows into SQLite.")
    print(f"Output: {config.OBSERVATIONS_JSON}")


if __name__ == "__main__":
    main()
