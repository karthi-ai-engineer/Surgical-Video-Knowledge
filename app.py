"""Surgical Video RAG — Streamlit demo (Phase 5 UI + Phase 6 physician review).

Run:  ./.venv/bin/streamlit run app.py

One page: video player (with jump-to-timestamp), a question box with 3 retrieval modes,
a grounded answer, video + document evidence, and an inline approve/edit/reject workflow.
Answers are computed only on "Ask" and cached in session state, so jump/review reruns
never trigger a paid LLM call.
"""
from __future__ import annotations

import streamlit as st

import config
from pipeline.answer import generate_answer
from pipeline.db import update_review, review_counts
from pipeline.util import fmt_range, fmt_ts

st.set_page_config(page_title="Surgical Video RAG Demo", layout="wide")

# --- Session state defaults ---
st.session_state.setdefault("seek", 0)
st.session_state.setdefault("result", None)
st.session_state.setdefault("editing", None)  # obs id currently being edited

VIDEO_OK = config.VIDEO_PATH.exists()
INDEX_OK = (config.DATA_DIR / "video_index.npy").exists()


_TYPE_COLOR = {
    "anatomy": "#ef9a9a", "instrument": "#90caf9", "phase": "#a5d6a7",
    "action": "#ffcc80", "safety-step": "#ce93d8", "complication": "#eeeeee",
}
_PROV_COLOR = {"backbone": "#000000", "document": "#1565c0", "video": "#2e7d32"}


def _graph_dot(sub: dict) -> str:
    """Build a Graphviz DOT string for a query subgraph (seeds highlighted, edges
    colored by provenance: black=backbone, blue=document, green=video)."""
    from pipeline.graph import ONTOLOGY
    seeds = set(sub.get("seeds", []))
    out = ["digraph G {", "rankdir=LR; bgcolor=transparent;",
           'node [style=filled, shape=box, fontname=Helvetica, fontsize=10];']
    for n in sub.get("nodes", []):
        ntype = ONTOLOGY.get(n, ("", []))[0]
        fill = _TYPE_COLOR.get(ntype, "#eeeeee")
        border = ', color="#d32f2f", penwidth=3' if n in seeds else ""
        label = n.replace('"', "'")
        out.append(f'"{label}" [fillcolor="{fill}"{border}];')
    for e in sub.get("edges", []):
        c = _PROV_COLOR.get(e.get("prov"), "#999999")
        s = e["source"].replace('"', "'"); t = e["target"].replace('"', "'")
        out.append(f'"{s}" -> "{t}" [label="{e["relation"]}", color="{c}", '
                   f'fontcolor="{c}", fontsize=8];')
    out.append("}")
    return "\n".join(out)


def _do_review(obs_id: int, status: str, text: str | None = None):
    update_review(obs_id, status, text)
    # Keep the cached result's evidence card in sync with the DB so the badge/text
    # updates on rerun WITHOUT triggering a new (paid) retrieval. (review-agent H1)
    res = st.session_state.result
    if res:
        for v in res.get("video_evidence", []):
            if v.get("id") == obs_id:
                v["review_status"] = status
                v["reviewed_text"] = text if status == "edited" else None
    st.session_state.editing = None
    st.toast(f"Observation #{obs_id} → {status}")


# ============================ Sidebar ============================
with st.sidebar:
    st.header("Case")
    st.write(f"**Procedure:** {config.PROCEDURE}")
    if VIDEO_OK:
        st.write(f"**Video:** `{config.VIDEO_PATH.name}`")
    st.divider()
    st.subheader("Review status")
    counts = review_counts()
    st.write(
        f"- ✅ approved: **{counts.get('approved', 0)}**\n"
        f"- ✏️ edited: **{counts.get('edited', 0)}**\n"
        f"- ❌ rejected: **{counts.get('rejected', 0)}**\n"
        f"- ⬜ unreviewed: **{counts.get('unreviewed', 0)}**"
    )
    st.caption("Edited-text search requires an index rebuild "
               "(`scripts/build_index.py`). Approve/reject apply live.")

# ============================ Header + player ============================
st.title("🔬 Surgical Video RAG Demo")

if not VIDEO_OK:
    st.error(f"Video not found at `{config.VIDEO_PATH}`. Add it and reload.")
if not INDEX_OK:
    st.warning("Search index not found. Run `./.venv/bin/python scripts/build_index.py`.")

left, right = st.columns([3, 2])

with left:
    if VIDEO_OK:
        st.video(str(config.VIDEO_PATH), start_time=int(st.session_state.seek))
        if st.session_state.seek:
            st.caption(f"⏱ Player positioned at **{fmt_ts(st.session_state.seek)}**")

with right:
    st.subheader("Ask this surgery")
    query = st.text_input("Question", key="query",
                          placeholder="e.g. Where does clipping begin?")
    mode = st.radio("Mode", ["Combined", "Video", "Knowledge"], horizontal=True)
    reviewed_only = st.checkbox(
        "Reviewed video observations only",
        disabled=(mode == "Knowledge"),  # no video retrieval in Knowledge mode (review-agent L7)
        help="Restrict VIDEO evidence to approved/edited observations. "
             "No effect in Knowledge mode.")
    if st.button("Ask", type="primary", disabled=not INDEX_OK):
        if query.strip():
            st.session_state.editing = None  # don't leak edit state across questions (M3)
            with st.spinner("Retrieving evidence and generating a grounded answer…"):
                st.session_state.result = generate_answer(
                    query, mode=mode.lower(), reviewed_only=reviewed_only)
        else:
            st.warning("Enter a question first.")

# ============================ Results ============================
res = st.session_state.result
if res:
    st.divider()
    st.subheader("Answer")
    if res.get("insufficient"):
        st.info(res["answer"])
    else:
        st.markdown(res["answer"])

    ev_col1, ev_col2 = st.columns(2)

    # ---- Video evidence + inline review ----
    with ev_col1:
        st.markdown("### 🎬 Video evidence")
        if not res["video_evidence"]:
            st.caption("No video evidence for this query/mode.")
        for i, v in enumerate(res["video_evidence"]):  # index-based keys (review-agent M2)
            anchor = " ⭐" if v.get("temporal_anchor") else ""
            status = v.get("review_status", "unreviewed")
            badge = {"approved": "✅", "edited": "✏️", "rejected": "❌"}.get(status, "⬜")
            with st.container(border=True):
                st.markdown(f"**▶ {fmt_range(v['start_sec'], v['end_sec'])}**{anchor} "
                            f"— {v['phase']}  {badge}")
                st.caption(f"Instruments: {', '.join(v.get('instruments') or []) or '—'}")
                text = v.get("reviewed_text") if status == "edited" else v["observation"]
                st.write(text)

                oid = v.get("id")
                b1, b2, b3, b4 = st.columns(4)
                if b1.button("Jump", key=f"jump_{i}"):
                    st.session_state.seek = int(v["start_sec"])
                    st.rerun()
                if oid is not None:
                    if b2.button("Approve", key=f"appr_{i}"):
                        _do_review(oid, "approved"); st.rerun()
                    if b3.button("Edit", key=f"edit_{i}"):
                        st.session_state.editing = oid; st.rerun()
                    if b4.button("Reject", key=f"rej_{i}"):
                        _do_review(oid, "rejected"); st.rerun()

                if st.session_state.editing == oid and oid is not None:
                    new_text = st.text_area("Edit observation", value=text, key=f"ta_{i}")
                    s1, s2 = st.columns(2)
                    if s1.button("Save", key=f"save_{i}"):
                        if new_text.strip():                      # guard empty save (L8)
                            _do_review(oid, "edited", new_text); st.rerun()
                        else:
                            st.warning("Edited text cannot be empty.")
                    if s2.button("Cancel", key=f"cancel_{i}"):
                        st.session_state.editing = None; st.rerun()

    # ---- Document evidence ----
    with ev_col2:
        st.markdown("### 📄 Document evidence")
        if not res["document_evidence"]:
            st.caption("No document evidence for this query/mode.")
        for d in res["document_evidence"]:
            page = f" · p{d['page']}" if d.get("page") else ""
            with st.container(border=True):
                st.markdown(f"**{d['document_name']}**{page}")
                st.write(d["chunk_text"][:500] + ("…" if len(d["chunk_text"]) > 500 else ""))

    # ---- Knowledge graph (supplementary, additive layer) ----
    if res.get("graph"):
        st.divider()
        with st.expander("🕸 Knowledge graph — how these concepts connect (supplementary)",
                         expanded=True):
            st.graphviz_chart(_graph_dot(res["graph"]))
            st.caption("Edges: **black** = guideline backbone · **blue** = extracted from "
                       "documents · **green** = observed in this video. Red-outlined nodes "
                       "matched your question. This graph supplements — it does not replace — "
                       "the cited evidence above.")

# ============================ Footer ============================
st.divider()
st.caption(
    "Demo for surgical education, review, and information retrieval. "
    "AI-generated video observations require expert validation. "
    "Not intended for diagnosis or treatment decisions."
)
