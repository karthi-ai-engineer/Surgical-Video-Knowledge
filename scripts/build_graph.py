"""Phase 8 entrypoint: build the GraphRAG knowledge graph.

Ontology nodes + seeded backbone + deterministic video edges + LLM-extracted document
edges (content-hash cached). Persists to data/graph.json.

    ./.venv/bin/python scripts/build_graph.py            # full (with LLM doc extraction)
    ./.venv/bin/python scripts/build_graph.py --no-llm   # deterministic only (instant)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.graph import build_graph, GRAPH_JSON

if __name__ == "__main__":
    use_llm = "--no-llm" not in sys.argv
    print(f"Building graph (LLM doc extraction: {use_llm})...")
    g = build_graph(use_llm=use_llm)
    from collections import Counter
    origins = Counter(d.get("origin") for _, _, d in g.edges(data=True))
    print(f"OK: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges -> {GRAPH_JSON}")
    print(f"    edge origins: {dict(origins)}")
