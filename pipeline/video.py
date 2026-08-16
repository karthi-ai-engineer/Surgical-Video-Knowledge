"""Phase 1a: probe the video and extract timestamped frames with the bundled ffmpeg.
No AI here — just deterministic frame extraction. Frame filenames encode the second."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

import config


@dataclass
class VideoInfo:
    duration_sec: float
    fps: float
    width: int
    height: int


def _ffprobe_bin() -> str:
    # imageio-ffmpeg ships ffmpeg; ffprobe usually sits next to it. Fall back to `ffprobe`.
    ff = Path(config.FFMPEG_BIN)
    candidate = ff.with_name("ffprobe")
    return str(candidate) if candidate.exists() else "ffprobe"


def probe_video(video_path: Path = config.VIDEO_PATH) -> VideoInfo:
    """Read duration/fps/resolution. Uses ffprobe if available, else parses ffmpeg output."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    probe = _ffprobe_bin()
    try:
        out = subprocess.run(
            [probe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(video_path)],
            capture_output=True, text=True, check=True,
        ).stdout
        meta = json.loads(out)
        vstream = next(s for s in meta["streams"] if s.get("codec_type") == "video")
        num, den = (vstream.get("r_frame_rate", "0/1").split("/") + ["1"])[:2]
        fps = float(num) / float(den) if float(den) else 0.0
        duration = float(meta["format"].get("duration") or vstream.get("duration") or 0.0)
        return VideoInfo(duration, fps, int(vstream["width"]), int(vstream["height"]))
    except Exception:
        # Fallback: ffmpeg writes stream info to stderr.
        res = subprocess.run(
            [config.FFMPEG_BIN, "-i", str(video_path)],
            capture_output=True, text=True,
        )
        return _parse_ffmpeg_stderr(res.stderr)


def _parse_ffmpeg_stderr(stderr: str) -> VideoInfo:
    import re
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
    if m:
        h, mm, s = m.groups()
        duration = int(h) * 3600 + int(mm) * 60 + float(s)
    fps = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
    if m:
        fps = float(m.group(1))
    w = h = 0
    m = re.search(r"(\d{2,5})x(\d{2,5})", stderr)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    return VideoInfo(duration, fps, w, h)


def extract_frames(
    video_path: Path = config.VIDEO_PATH,
    interval_sec: int = config.COARSE_INTERVAL_SEC,
    width: int = config.FRAME_WIDTH,
    start_sec: int = 0,
    end_sec: int | None = None,
) -> List[int]:
    """Extract 1 frame every `interval_sec`, downscaled to `width`px.

    Frames are written to data/frames/frame_SSSSSS.jpg where SSSSSS = the second.
    Resumable: frames that already exist on disk are skipped (re-run is cheap).
    Returns the sorted list of second-timestamps that now have a frame on disk.
    """
    config.FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    info = probe_video(video_path)
    duration = info.duration_sec or 0.0
    # Stop ~1s before the reported end to avoid EOF-seek failures on the final frame.
    last = int(duration) - 1 if duration > 1 else int(duration)
    if end_sec is not None:
        last = min(last, end_sec)
    if last < start_sec:
        last = start_sec

    tmp_dir = config.FRAMES_DIR
    # Resumable: only extract MISSING frames. Frame filename encodes the exact second,
    # and -ss before -i does an exact input seek to that second.
    targets = list(range(start_sec, last + 1, interval_sec))
    missing = [t for t in targets if not (tmp_dir / f"frame_{t:06d}.jpg").exists()]

    if missing:
        print(f"Extracting {len(missing)} frames "
              f"({len(targets) - len(missing)} already on disk)...")
    failed = []
    for i, t in enumerate(missing, 1):
        out_path = tmp_dir / f"frame_{t:06d}.jpg"
        try:
            subprocess.run(
                [config.FFMPEG_BIN, "-nostdin", "-loglevel", "error",
                 "-ss", str(t), "-i", str(video_path),
                 "-frames:v", "1",
                 "-vf", f"scale={width}:-1",
                 "-q:v", "3", "-y", str(out_path)],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            failed.append(t)  # tolerate the odd unreadable timestamp; keep going
        if i % 100 == 0:
            print(f"  ...{i}/{len(missing)} frames extracted")

    if failed:
        print(f"  note: {len(failed)} frame(s) could not be extracted and were skipped "
              f"(e.g. {failed[:3]})")

    return sorted(t for t in targets if (tmp_dir / f"frame_{t:06d}.jpg").exists())


def frame_path(second: int) -> Path:
    return config.FRAMES_DIR / f"frame_{second:06d}.jpg"
