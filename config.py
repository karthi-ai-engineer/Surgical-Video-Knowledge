"""Central config: paths, models, sampling params. Budget-first defaults."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
PAPERS_DIR = DATA_DIR / "papers"
FRAMES_DIR = DATA_DIR / "frames"
CHUNKS_DIR = DATA_DIR / "chunks"
OBSERVATIONS_JSON = DATA_DIR / "observations.json"
VIDEO_PATH = DATA_DIR / "surgery.mp4"
DB_PATH = ROOT / "db" / "demo.db"

# --- Models (override via .env; defaults are the cheap mini tier) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o-mini")
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

# --- FFmpeg (bundled in-venv via imageio-ffmpeg; nothing installed system-wide) ---
def _ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return os.getenv("FFMPEG_BIN", "ffmpeg")  # fallback to system ffmpeg if present


FFMPEG_BIN = _ffmpeg_bin()

# --- Sampling ---
# Medical video: sample densely (1 fps) so no event is missed. Segment boundaries
# are resolved to ~BATCH_SIZE seconds. Cost scales with video length (see PROJECT_PLAN).
COARSE_INTERVAL_SEC = 1     # 1 frame every 1s (dense, accuracy-first)
FRAME_WIDTH = 512           # resize before sending to vision API (cost control)
BATCH_SIZE = 5              # frames per vision call -> 5s observation window

# --- Fine pass (Phase 7 stretch) ---
FINE_INTERVAL_SEC = 5

# --- Document chunking (Phase 3) ---
DOC_CHUNK_CHARS = 1200      # approx chunk size in characters
DOC_CHUNK_OVERLAP = 200     # overlap between consecutive chunks

# --- Surgical phase enum ---
PHASES = [
    "Preparation",
    "Calot triangle dissection",
    "Clipping and cutting",
    "Gallbladder dissection",
    "Gallbladder retraction",
    "Cleaning and coagulation",
    "Gallbladder packaging",
    "Unknown",
]

PROCEDURE = "Laparoscopic cholecystectomy"
