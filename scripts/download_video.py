"""Download a source video to data/surgery.mp4 using yt-dlp + the bundled ffmpeg.

Local, single-video demo use only — respect the source video's license; do not redistribute.

    ./.venv/bin/python scripts/download_video.py <youtube_url> [browser]

`browser` (optional) reads cookies from a logged-in browser for age-restricted videos,
e.g. chrome, safari, firefox, edge, brave.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def download(url: str, browser: str | None = None, cookies_file: str | None = None) -> Path:
    import yt_dlp

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = config.VIDEO_PATH  # data/surgery.mp4
    ffmpeg_dir = str(Path(config.FFMPEG_BIN).parent)

    opts = {
        # Prefer a single mp4 up to 720p (plenty — we downscale to 512px anyway); keeps it small/cheap.
        "format": "best[ext=mp4][height<=720]/best[height<=720]/best",
        "outtmpl": str(out.with_suffix("")) + ".%(ext)s",
        "merge_output_format": "mp4",
        "ffmpeg_location": ffmpeg_dir,
        "quiet": False,
        "noprogress": False,
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file
    elif browser:
        opts["cookiesfrombrowser"] = (browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Normalize whatever extension we got to data/surgery.mp4
    if not out.exists():
        for cand in config.DATA_DIR.glob("surgery.*"):
            if cand.suffix.lower() in (".mp4", ".mkv", ".webm"):
                cand.rename(out)
                break

    dur = info.get("duration")
    print(f"\nSaved: {out}")
    if dur:
        print(f"Duration: {dur}s (~{dur/60:.1f} min)")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/download_video.py <url> [browser|cookies.txt]")
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if arg and (arg.endswith(".txt") or Path(arg).exists()):
        download(sys.argv[1], cookies_file=arg)
    else:
        download(sys.argv[1], browser=arg)
