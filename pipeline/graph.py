"""Phase 8: lightweight, self-contained GraphRAG layer (ADDITIVE).

Design (from the Phase-8 design debate):
- A CLOSED canonical ontology (fixed concept nodes + aliases) is the entity-resolution
  backbone — the LLM extractor may only map text to these ids or drop it, so no node
  explosion.
- Video observations are already structured (phase + instruments), so they link to
  concept nodes DETERMINISTICALLY (no LLM) — the unique cross-modal video<->doc join.
- A small SEEDED backbone guarantees flagship guideline facts (CVS criteria etc.).
- Real LLM extraction over doc chunks adds breadth; results are content-hash cached.
- Retrieval is additive: query -> entity-link -> <=2-hop subgraph as SUPPLEMENTARY
  structured evidence. No entity match -> inject nothing -> vector path untouched.

Storage: networkx DiGraph serialized to data/graph.json (pure-python, in-venv).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import List, Optional

import networkx as nx

import config
from pipeline.db import get_conn
from pipeline.util import fmt_range

GRAPH_JSON = config.DATA_DIR / "graph.json"
EDGE_CACHE = config.DATA_DIR / "graph_edge_cache.json"

# ------------------------------------------------------------------ Ontology
# node id -> (type, [aliases]). ids are the canonical display labels.
ONTOLOGY = {
    # anatomy
    "hepatocystic triangle": ("anatomy", ["calot's triangle", "calot triangle", "hepatocystic"]),
    "cystic duct": ("anatomy", ["cystic ducts"]),
    "cystic artery": ("anatomy", ["cystic arteries"]),
    "common bile duct": ("anatomy", ["cbd", "common bile ducts"]),
    "common hepatic duct": ("anatomy", ["chd"]),
    "gallbladder": ("anatomy", ["cholecyst", "gb"]),
    "cystic plate": ("anatomy", ["gallbladder plate"]),
    "liver bed": ("anatomy", ["gallbladder fossa", "liver bed"]),
    # instruments
    "clip applier": ("instrument", ["clip appliers", "clip", "clips", "clipper"]),
    "grasper": ("instrument", ["graspers", "forceps"]),
    "hook": ("instrument", ["l-hook", "hook electrocautery"]),
    "scissors": ("instrument", ["scissor"]),
    "dissector": ("instrument", ["maryland", "dissecting forceps"]),
    "coagulation device": ("instrument", ["electrocautery", "cautery", "diathermy", "energy device"]),
    "retrieval bag": ("instrument", ["endobag", "specimen bag", "extraction bag"]),
    "trocar": ("instrument", ["trocars", "port", "ports"]),
    # phases
    "Preparation": ("phase", []),
    "Calot triangle dissection": ("phase", ["calot dissection"]),
    "Clipping and cutting": ("phase", ["clipping", "clipping phase"]),
    "Gallbladder dissection": ("phase", ["gb dissection"]),
    "Gallbladder retraction": ("phase", ["gb retraction"]),
    "Cleaning and coagulation": ("phase", ["hemostasis", "irrigation"]),
    "Gallbladder packaging": ("phase", ["specimen retrieval", "gb packaging"]),
    # actions
    "dissection": ("action", ["dissect", "dissecting"]),
    "retraction": ("action", ["retract", "retracting"]),
    "clipping": ("action", ["clip application", "applying clips"]),
    "cutting": ("action", ["division", "transection", "cut"]),
    "coagulation": ("action", ["coagulate", "cauterization"]),
    # safety steps / concepts
    "Critical View of Safety": ("safety-step", ["cvs", "critical view"]),
    "CVS criterion: two structures": ("safety-step",
        ["two structures entering the gallbladder", "two and only two structures", "two tubular structures"]),
    "CVS criterion: hepatocystic triangle cleared": ("safety-step",
        ["clearance of the hepatocystic triangle", "triangle cleared of fat and fibrous tissue"]),
    "CVS criterion: cystic plate exposed": ("safety-step",
        ["lower third of the cystic plate", "cystic plate exposed", "lower part of the gallbladder separated"]),
    "intraoperative cholangiography": ("safety-step", ["ioc", "cholangiography", "intraoperative cholangiogram"]),
    "conversion to open": ("safety-step", ["conversion", "open cholecystectomy", "convert to open"]),
    "time-out": ("safety-step", ["surgical pause", "momentum stop"]),
    # complications
    "bile duct injury": ("complication", ["bdi", "biliary injury", "common bile duct injury"]),
    "bleeding": ("complication", ["hemorrhage", "haemorrhage"]),
    "bile leak": ("complication", ["biliary leak", "bile leakage"]),
}

ALLOWED_RELATIONS = [
    "requires_before", "applied_to", "causes", "prevents", "part_of",
    "occurs_in_phase", "uses_instrument", "located_in", "reduces_risk_of",
]

# Plausible (source_type -> target_type) constraints per relation. LLM-extracted edges that
# violate these are dropped, which removes most extraction noise (e.g. an anatomy node
# "causing" nothing, or a complication "reducing risk"). Backbone/video edges bypass this.
RELATION_TYPE_RULES = {
    "prevents":        ({"safety-step"}, {"complication"}),
    "reduces_risk_of": ({"safety-step", "action"}, {"complication"}),
    "causes":          ({"action", "complication"}, {"complication"}),
    "applied_to":      ({"instrument"}, {"anatomy"}),
    "uses_instrument": ({"phase", "action"}, {"instrument"}),
    "occurs_in_phase": ({"action", "instrument", "safety-step"}, {"phase"}),
    "requires_before": ({"phase", "action", "safety-step"}, {"safety-step", "phase", "action"}),
    "part_of":         ({"safety-step", "anatomy", "action"}, {"safety-step", "anatomy"}),
    "located_in":      ({"anatomy"}, {"anatomy"}),
}

# Authoritative seeded backbone — guarantees the flagship multi-hop facts regardless of
# extraction. Each is well-established guideline knowledge.
BACKBONE_EDGES = [
    ("Clipping and cutting", "requires_before", "Critical View of Safety"),
    ("cutting", "requires_before", "Critical View of Safety"),
    ("Critical View of Safety", "part_of", "CVS criterion: two structures"),
    ("Critical View of Safety", "part_of", "CVS criterion: hepatocystic triangle cleared"),
    ("Critical View of Safety", "part_of", "CVS criterion: cystic plate exposed"),
    ("Critical View of Safety", "prevents", "bile duct injury"),
    ("intraoperative cholangiography", "reduces_risk_of", "bile duct injury"),
    ("clip applier", "applied_to", "cystic duct"),
    ("clip applier", "applied_to", "cystic artery"),
    ("cystic duct", "located_in", "hepatocystic triangle"),
    ("cystic artery", "located_in", "hepatocystic triangle"),
    ("bile duct injury", "causes", "bile leak"),
]

# An alias can legitimately map to MORE THAN ONE node (e.g. "clipping" -> both the
# "Clipping and cutting" phase and the "clipping" action), so map alias -> list of ids.
_ALIAS_TO_IDS: dict = {}
for _id, (_t, _aliases) in ONTOLOGY.items():
    for _key in [_id.lower()] + [a.lower() for a in _aliases]:
        _ALIAS_TO_IDS.setdefault(_key, [])
        if _id not in _ALIAS_TO_IDS[_key]:
            _ALIAS_TO_IDS[_key].append(_id)


def canonicalize(label: str) -> Optional[str]:
    """Map a raw label/alias to a single canonical ontology id, or None if unknown.
    Prefers an exact canonical-id match, else the first node the alias refers to."""
    if not label:
        return None
    key = label.strip().lower()
    if key in ONTOLOGY_LOWER:
        return ONTOLOGY_LOWER[key]
    ids = _ALIAS_TO_IDS.get(key)
    return ids[0] if ids else None


def mentioned_nodes(text: str) -> List[str]:
    """All canonical node ids whose id/alias appears in text, matched on WORD BOUNDARIES
    (so 'clipping?' or 'gallbladder.' still match; optional trailing 's' for plurals)."""
    t = (text or "").lower()
    out, seen = [], set()
    for alias, ids in _ALIAS_TO_IDS.items():
        if len(alias) < 3:
            continue
        if re.search(r"\b" + re.escape(alias) + r"s?\b", t):
            for nid in ids:
                if nid not in seen:
                    seen.add(nid); out.append(nid)
    return out


ONTOLOGY_LOWER = {k.lower(): k for k in ONTOLOGY}


# ------------------------------------------------------------------ LLM extraction
def _ontology_prompt() -> str:
    by_type: dict = {}
    for nid, (t, _a) in ONTOLOGY.items():
        by_type.setdefault(t, []).append(nid)
    lines = [f"{t}: {', '.join(ids)}" for t, ids in by_type.items()]
    return ("CANONICAL NODES (use ONLY these exact labels as source/target):\n"
            + "\n".join(lines)
            + "\n\nALLOWED RELATIONS: " + ", ".join(ALLOWED_RELATIONS))


_EXTRACT_SYSTEM = (
    "You extract a knowledge graph about laparoscopic cholecystectomy from text. "
    "Return ONLY relationships where BOTH the source and target are in the canonical node "
    "list, and the relation is in the allowed list. Map synonyms to the canonical label. "
    "DROP anything that does not map cleanly — do not invent nodes or relations. "
    "Only include relationships the text actually supports.\n\n" + _ontology_prompt() +
    "\n\nReturn JSON: {\"edges\": [{\"source\": <label>, \"relation\": <rel>, \"target\": <label>}]}"
)


def _hash(texts: List[str]) -> str:
    return hashlib.sha1("\n\n".join(texts).encode()).hexdigest()


def _load_edge_cache() -> dict:
    return json.loads(EDGE_CACHE.read_text()) if EDGE_CACHE.exists() else {}


def _save_edge_cache(cache: dict) -> None:
    EDGE_CACHE.write_text(json.dumps(cache))


def extract_doc_edges(batch_size: int = 6) -> List[dict]:
    """LLM-extract ontology-constrained edges from the document chunks. Content-hash
    cached per batch, so re-runs are free. Returns list of {source,relation,target,documents}."""
    import json as _json
    from pipeline.index import get_client
    from pipeline.documents import load_all_chunks

    chunks = load_all_chunks()
    cache = _load_edge_cache()
    all_edges: List[dict] = []

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c.chunk_text for c in batch]
        docs = sorted({c.document_name for c in batch})
        key = _hash(texts)
        if key in cache:
            raw_edges = cache[key]
        else:
            blob = "\n\n---\n\n".join(texts)
            try:
                resp = get_client().chat.completions.create(
                    model=config.ANSWER_MODEL,
                    messages=[{"role": "system", "content": _EXTRACT_SYSTEM},
                              {"role": "user", "content": blob[:12000]}],
                    response_format={"type": "json_object"}, temperature=0.0,
                )
                raw_edges = _json.loads(resp.choices[0].message.content).get("edges", [])
            except Exception:
                raw_edges = []
            cache[key] = raw_edges
            _save_edge_cache(cache)

        for e in raw_edges:
            s = canonicalize(e.get("source", ""))
            r = (e.get("relation") or "").strip()
            t = canonicalize(e.get("target", ""))
            if not (s and t and s != t and r in ALLOWED_RELATIONS):
                continue
            rule = RELATION_TYPE_RULES.get(r)
            if rule and not (ONTOLOGY[s][0] in rule[0] and ONTOLOGY[t][0] in rule[1]):
                continue  # drop type-implausible extracted edge (noise control)
            all_edges.append({"source": s, "relation": r, "target": t, "documents": docs})
    return all_edges


# ------------------------------------------------------------------ Build / load
def _video_edges() -> List[dict]:
    """Deterministic cross-modal edges from the (already structured) video observations:
    phase --uses_instrument--> instrument, weighted, with example timestamps. No LLM."""
    agg: dict = {}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT start_sec, end_sec, phase, instruments FROM video_observations "
            "WHERE review_status != 'rejected'").fetchall()
    for r in rows:
        phase = canonicalize(r["phase"])
        if not phase:
            continue
        for inst in json.loads(r["instruments"] or "[]"):
            ci = canonicalize(inst)
            if not ci:
                continue
            k = (phase, ci)
            d = agg.setdefault(k, {"count": 0, "timestamps": []})
            d["count"] += 1
            if len(d["timestamps"]) < 5:
                d["timestamps"].append(fmt_range(r["start_sec"], r["end_sec"]))
    return [{"source": p, "relation": "uses_instrument", "target": i,
             "count": v["count"], "timestamps": v["timestamps"]}
            for (p, i), v in agg.items()]


def build_graph(use_llm: bool = True) -> nx.DiGraph:
    """Assemble the graph: ontology nodes + seeded backbone + deterministic video edges
    + (optionally) LLM-extracted document edges. Persist to data/graph.json."""
    g = nx.DiGraph()
    for nid, (t, _a) in ONTOLOGY.items():
        g.add_node(nid, type=t)

    for s, r, t in BACKBONE_EDGES:
        g.add_edge(s, t, relation=r, origin="backbone")

    for e in _video_edges():
        g.add_edge(e["source"], e["target"], relation=e["relation"],
                   origin="video", count=e["count"], timestamps=e["timestamps"])

    if use_llm:
        for e in extract_doc_edges():
            s, t = e["source"], e["target"]
            if g.has_edge(s, t) and g[s][t].get("origin") in ("backbone", "video"):
                continue  # don't overwrite authoritative/video edges
            if g.has_edge(t, s):
                continue  # drop reverse-direction duplicate (extraction noise)
            g.add_edge(s, t, relation=e["relation"],
                       origin="document", documents=e.get("documents", []))

    GRAPH_JSON.write_text(json.dumps(nx.node_link_data(g)))
    return g


def load_graph() -> nx.DiGraph:
    if not GRAPH_JSON.exists():
        raise RuntimeError("Graph not built. Run: ./.venv/bin/python scripts/build_graph.py")
    return nx.node_link_graph(json.loads(GRAPH_JSON.read_text()), directed=True)


# ------------------------------------------------------------------ Additive retrieval
def subgraph_for_query(query: str, hops: int = 2, max_edges: int = 20):
    """Return (context_text, subgraph_dict) for the query, or (None, None) if no entity
    matches — in which case the caller injects nothing and the vector path is untouched."""
    seeds = mentioned_nodes(query)
    if not seeds:
        return None, None
    try:
        g = load_graph()
    except RuntimeError:
        return None, None
    seeds = [s for s in seeds if s in g]
    if not seeds:
        return None, None

    und = g.to_undirected()
    nodes = set(seeds)
    for s in seeds:
        nodes |= set(nx.single_source_shortest_path_length(und, s, cutoff=hops).keys())

    # Prioritise edges: seed-incident first, then authoritative (backbone/document) over
    # video, so flagship facts (e.g. CVS -> its criteria) are never crowded out by video
    # instrument noise. Cap video edges so the context stays focused.
    seed_set = set(seeds)
    cand = [(u, v, d) for u, v, d in g.edges(data=True) if u in nodes and v in nodes]

    def _prio(e):
        u, v, d = e
        seed_incident = 0 if (u in seed_set or v in seed_set) else 1
        origin_rank = {"backbone": 0, "document": 1, "video": 2}.get(d.get("origin"), 3)
        return (seed_incident, origin_rank)

    cand.sort(key=_prio)

    lines, viz_edges, vid_count = [], [], 0
    for u, v, d in cand:
        prov = d.get("origin", "")
        if prov == "video":
            if vid_count >= 6:
                continue
            vid_count += 1
        extra = ""
        if prov == "video" and d.get("timestamps"):
            extra = f" (seen in video at {', '.join(d['timestamps'][:3])})"
        elif prov == "document" and d.get("documents"):
            extra = f" (from {', '.join(d['documents'][:1])})"
        lines.append(f"- {u} --{d['relation']}--> {v}{extra}")
        viz_edges.append({"source": u, "target": v, "relation": d["relation"], "prov": prov})
        if len(lines) >= max_edges:
            break
    if not lines:
        return None, None
    text = ("NON-CITABLE STRUCTURED HINTS (knowledge-graph connections — do NOT cite these "
            "as a source; re-ground every claim in the video timestamps or named documents "
            "above):\n" + "\n".join(lines))
    return text, {"seeds": seeds, "nodes": sorted(nodes), "edges": viz_edges}


if __name__ == "__main__":
    g = build_graph(use_llm=False)
    print(f"Graph (deterministic only): {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

