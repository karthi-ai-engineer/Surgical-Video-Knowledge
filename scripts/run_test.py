"""Test runner: ask the bot each question in data/test_set.json and record its answer
+ evidence. Writes data/test_run_results.json for the verification step.

    ./.venv/bin/python scripts/run_test.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.answer import generate_answer
from pipeline.util import fmt_range

SET = config.DATA_DIR / "test_set.json"
OUT = config.DATA_DIR / "test_run_results.json"


def main():
    questions = json.loads(SET.read_text())
    results = []
    for item in questions:
        r = generate_answer(item["q"], mode=item.get("mode", "combined"))
        ve = [{"range": fmt_range(v["start_sec"], v["end_sec"]),
               "start_sec": v["start_sec"], "phase": v["phase"],
               "anchor": bool(v.get("temporal_anchor"))}
              for v in r["video_evidence"]]
        ds = [{"document": d["document_name"], "page": d.get("page")}
              for d in r["document_evidence"]]
        results.append({
            "num": item["num"], "q": item["q"], "mode": item["mode"],
            "required": item["required"], "key_facts": item["key_facts"],
            "bot_answer": r["answer"],
            "video_evidence": ve, "doc_sources": ds,
            "graph_nodes": len(r["graph"]["nodes"]) if r.get("graph") else 0,
            "insufficient": r["insufficient"],
        })
        print(f"[{item['num']}/{len(questions)}] asked: {item['q'][:50]}")
    OUT.write_text(json.dumps(results, indent=2))
    print(f"\nWROTE {OUT} ({len(results)} results)")


if __name__ == "__main__":
    main()
