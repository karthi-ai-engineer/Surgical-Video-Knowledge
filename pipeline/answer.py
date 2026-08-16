"""Phase 4: grounded answer generation over retrieved video + document evidence.

Design (from the Phase-4 design debate):
- Semantic retrieval is the default for every query.
- A tightly-scoped, NON-destructive temporal-anchor path guarantees correctness on
  "begin/first/when" (and "last/end") questions by doing an exact argmin/argmax over
  start_sec in SQLite for the mapped phase. It only ADDS a row; it never suppresses
  semantic hits, and it stays inert when intent or phase don't map cleanly.
- Video evidence is presented chronologically; the prompt is grounded and refuses
  diagnosis/treatment regardless of what the user asks.
"""
from __future__ import annotations

import json
import re
import time
from typing import List, Optional

import config
from pipeline.index import get_client
from pipeline.retrieve import search_video, search_documents
from pipeline.db import get_conn
from pipeline.util import fmt_range

VALID_MODES = ("combined", "video", "knowledge")

# --- Temporal intent detection ---------------------------------------------------
# Strong directional words decide earliest vs latest. Bare "when" is neutral (just asks
# for a time) and must NOT override a strong "end/last" signal, so it's matched separately
# and only defaults to earliest when no strong direction is present.
_EARLIEST = re.compile(
    r"\b(first|begin|begins|beginning|start|starts|started|starting|"
    r"earliest|initial|initially|onset)\b", re.I)
_LATEST = re.compile(
    r"\b(last|latest|end|ends|ending|final|finally|finish|finishes|completed)\b", re.I)
_WHEN = re.compile(r"\bwhen\b", re.I)


def _direction(query: str) -> Optional[str]:
    early = bool(_EARLIEST.search(query))
    late = bool(_LATEST.search(query))
    if late and not early:
        return "latest"
    if early:
        return "earliest"
    if _WHEN.search(query):  # neutral "when ...?" defaults to onset
        return "earliest"
    return None

# Map query wording -> one of the 8 canonical phases. Substring match, scored; a unique
# top scorer wins, otherwise we skip the anchor (fall through to pure semantic).
_PHASE_SYNONYMS = {
    "Preparation": ["preparation", "trocar", "port placement", "insufflation", "access"],
    "Calot triangle dissection": ["calot", "hepatocystic", "triangle"],
    "Clipping and cutting": ["clip", "clipping", "cutting", "cystic duct", "cystic artery"],
    "Gallbladder dissection": ["gallbladder dissection", "liver bed", "detach", "dissect gallbladder"],
    "Gallbladder retraction": ["retraction", "retract"],
    "Cleaning and coagulation": ["coagulation", "coagulate", "cleaning", "irrigation", "hemostasis", "bleeding"],
    "Gallbladder packaging": ["packaging", "retrieval bag", "specimen", "extraction bag"],
}


def _map_phase(query: str) -> Optional[str]:
    q = query.lower()
    scores = {ph: sum(1 for kw in kws if kw in q) for ph, kws in _PHASE_SYNONYMS.items()}
    best = max(scores.values())
    if best == 0:
        return None
    winners = [ph for ph, s in scores.items() if s == best]
    return winners[0] if len(winners) == 1 else None  # ambiguous -> skip


def temporal_anchor(query: str, reviewed_only: bool = False) -> Optional[dict]:
    """Return the earliest/latest observation of the phase the query refers to, or None.
    Deterministic and exact — this is what makes 'where does clipping begin?' correct."""
    direction = _direction(query)
    if not direction:
        return None
    phase = _map_phase(query)
    if not phase:
        return None

    order = "ASC" if direction == "earliest" else "DESC"
    where = "phase = ?"
    params: list = [phase]
    if reviewed_only:
        where += " AND review_status IN ('approved','edited')"
    row = None
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT * FROM video_observations WHERE {where} ORDER BY start_sec {order} LIMIT 1",
            params,
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["instruments"] = json.loads(d.get("instruments") or "[]")
    d["actions"] = json.loads(d.get("actions") or "[]")
    d["source_type"] = "video"
    d["temporal_anchor"] = direction
    d["score"] = 1.0
    return d


# --- Grounded generation ---------------------------------------------------------
SYSTEM_PROMPT = """You are a grounded assistant for a laparoscopic cholecystectomy education and \
review tool. Answer ONLY from the evidence provided in the user message. Follow these rules strictly:

- VIDEO EVIDENCE describes what was visually observed in THIS specific surgery. When you use it, cite \
the timestamp(s), e.g. 4:00-4:04.
- DOCUMENT EVIDENCE is general reference knowledge from trusted guidelines/literature. When you use it, \
name the source document.
- Clearly separate "observed in the video" from "reference guidance from the literature."
- Do NOT provide diagnosis, treatment recommendations, patient-management decisions, or surgeon-intent \
claims, even if the user asks. This is an educational/review tool, not clinical advice. If asked for \
those, briefly decline and answer only what the evidence supports.
- If a question asks whether to DO something to THIS patient (e.g. convert to open surgery, re-operate, \
prescribe, admit, manage), decline the patient-specific decision and present any relevant document \
evidence ONLY as general reference guidance from the literature. Do NOT say an action "could be \
considered" for this patient or otherwise apply guidance to this specific case.
- Do not claim visual certainty beyond what an observation states. If video evidence is unclear or \
absent for the question, say so.
- For "begin/first/start/when" questions, the EARLIEST relevant timestamp is the answer; for "last/end" \
questions, the latest. If a TEMPORAL ANCHOR is given, treat it as the authoritative earliest/latest.
- If the evidence is insufficient to answer, say that plainly and do not speculate.
- A "NON-CITABLE STRUCTURED HINTS" block (from a knowledge graph) may be provided. It is ONLY a \
navigational hint about how concepts connect. NEVER cite it as a source, never write phrases like \
"from the structured relationships/knowledge graph", and never assert a relationship that the cited \
video/document evidence does not itself support. Every factual claim in your answer must be grounded \
in — and attributed to — a video timestamp or a named document. If a hinted relationship is not \
backed by the cited evidence, omit it.
- Be concise and specific."""


def _fmt_video_ev(video_ev: List[dict]) -> str:
    if not video_ev:
        return "(none)"
    lines = []
    for v in video_ev:
        instr = ", ".join(v.get("instruments") or []) or "none noted"
        tag = "  [TEMPORAL ANCHOR: %s]" % v["temporal_anchor"] if v.get("temporal_anchor") else ""
        lines.append(
            f"- {fmt_range(v['start_sec'], v['end_sec'])} | Phase: {v['phase']} | "
            f"Instruments: {instr}{tag}\n    {v['observation']}"
        )
    return "\n".join(lines)


def _fmt_doc_ev(doc_ev: List[dict]) -> str:
    if not doc_ev:
        return "(none)"
    lines = []
    for d in doc_ev:
        page = f" p{d['page']}" if d.get("page") else ""
        lines.append(f"- [{d['document_name']}{page}]\n    {d['chunk_text']}")
    return "\n".join(lines)


def _call_llm(user_content: str, max_retries: int = 3) -> str:
    delay, last_err = 1.0, None
    for _ in range(max_retries):
        try:
            resp = get_client().chat.completions.create(
                model=config.ANSWER_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_err = e
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"Answer API failed after {max_retries} retries: {last_err}")


def generate_answer(
    query: str,
    mode: str = "combined",
    top_k_video: int = 5,
    top_k_docs: int = 3,
    reviewed_only: bool = False,
    use_graph: bool = True,
) -> dict:
    """Retrieve evidence per mode and produce a grounded, cited answer.
    Returns a dict: query, mode, answer, video_evidence, document_evidence,
    temporal_anchor, graph, insufficient."""
    query = (query or "").strip()
    mode = (mode or "combined").lower()
    if mode not in VALID_MODES:
        mode = "combined"

    result = {
        "query": query, "mode": mode, "answer": "",
        "video_evidence": [], "document_evidence": [],
        "temporal_anchor": None, "graph": None, "insufficient": False,
    }
    if not query:
        result["insufficient"] = True
        result["answer"] = "Please enter a question."
        return result

    # --- Retrieval ---
    video_ev: List[dict] = []
    anchor = None
    if mode in ("video", "combined"):
        video_ev = search_video(query, top_k=top_k_video, reviewed_only=reviewed_only)
        anchor = temporal_anchor(query, reviewed_only=reviewed_only)
        if anchor and not any(v["start_sec"] == anchor["start_sec"] for v in video_ev):
            video_ev.append(anchor)
        video_ev = sorted(video_ev, key=lambda v: v["start_sec"])  # chronological presentation

    doc_ev: List[dict] = []
    if mode in ("knowledge", "combined"):
        doc_ev = search_documents(query, top_k=top_k_docs)

    result["video_evidence"] = video_ev
    result["document_evidence"] = doc_ev
    result["temporal_anchor"] = anchor

    # --- No evidence: refuse gracefully without spending an LLM call ---
    if not video_ev and not doc_ev:
        result["insufficient"] = True
        result["answer"] = (
            "I don't have enough evidence to answer that from this surgery's observations "
            "or the reference documents."
        )
        return result

    # --- Additive GraphRAG layer (supplementary; falls back silently if no entity match) ---
    graph_text = None
    if use_graph:
        try:
            from pipeline.graph import subgraph_for_query
            graph_text, graph_viz = subgraph_for_query(query)
            result["graph"] = graph_viz
        except Exception:
            graph_text = None  # graph is strictly optional; never break the answer path

    # --- Grounded generation ---
    anchor_note = ""
    if anchor:
        anchor_note = (
            f"\nTEMPORAL ANCHOR ({anchor['temporal_anchor']} '{anchor['phase']}' window): "
            f"{fmt_range(anchor['start_sec'], anchor['end_sec'])} — treat this as the authoritative "
            f"{anchor['temporal_anchor']} timestamp for this phase.\n"
        )
    graph_block = f"\n{graph_text}\n" if graph_text else ""
    user_content = (
        f"USER QUESTION:\n{query}\n"
        f"{anchor_note}"
        f"\nVIDEO EVIDENCE (chronological, from this surgery):\n{_fmt_video_ev(video_ev)}\n"
        f"\nDOCUMENT EVIDENCE (reference guidelines):\n{_fmt_doc_ev(doc_ev)}\n"
        f"{graph_block}"
        f"\nAnswer the question grounded strictly in the evidence above."
    )
    result["answer"] = _call_llm(user_content)
    return result


def format_result(res: dict) -> str:
    """Pretty terminal rendering of a generate_answer result."""
    from pipeline.util import fmt_range as _fr
    out = [f"Q ({res['mode']}): {res['query']}", "", "ANSWER:", res["answer"]]
    if res["video_evidence"]:
        out += ["", "VIDEO EVIDENCE:"]
        for v in res["video_evidence"]:
            anc = "  ★anchor" if v.get("temporal_anchor") else ""
            out.append(f"  {_fr(v['start_sec'], v['end_sec'])}  {v['phase']}{anc}")
    if res["document_evidence"]:
        out += ["", "DOCUMENT EVIDENCE:"]
        for d in res["document_evidence"]:
            page = f" p{d['page']}" if d.get("page") else ""
            out.append(f"  {d['document_name']}{page}")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Show where clipping begins and explain what should be verified before clipping."
    print(format_result(generate_answer(q)))
