"""Fetch the 5 open-access guideline PDFs into data/papers/ (reproducible corpus).

All sources are open-access (Europe PMC render endpoints). Run once after cloning:
    ./.venv/bin/python scripts/download_papers.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

PAPERS = [
    ("https://europepmc.org/articles/PMC8190978?pdf=render", "wses_2020_bile_duct_injury_guideline.pdf"),
    ("https://europepmc.org/articles/PMC9377448?pdf=render", "critical_view_of_safety_lap_chole.pdf"),
    ("https://europepmc.org/articles/PMC7643471?pdf=render", "wses_2020_acute_calculous_cholecystitis.pdf"),
    ("https://europepmc.org/articles/PMC3429769?pdf=render", "tokyo_guidelines_cholecystitis_diagnostic_criteria.pdf"),
    ("https://europepmc.org/articles/PMC7925835?pdf=render", "bile_duct_injury_prevention_cholangiography.pdf"),
]


def main():
    config.PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    for url, fn in PAPERS:
        out = config.PAPERS_DIR / fn
        if out.exists():
            print(f"skip (exists): {fn}")
            continue
        print(f"downloading {fn} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=60).read()
        if not data.startswith(b"%PDF"):
            print(f"  WARNING: {fn} did not return a PDF (got {data[:8]!r})")
        out.write_bytes(data)
        print(f"  saved {len(data)//1024} KB -> {out}")
    print("done.")


if __name__ == "__main__":
    main()
