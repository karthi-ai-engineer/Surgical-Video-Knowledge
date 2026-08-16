"""Phase 0 entrypoint: create db/demo.db with the demo tables."""
import sys
from pathlib import Path

# Allow running as `python scripts/init_db.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.db import init_db

if __name__ == "__main__":
    init_db()
    print(f"OK: initialized {config.DB_PATH}")
