# Surgical Video RAG — Build Plan & Fixed Direction

> **Purpose of this file:** The single source of truth for building this project. Any agent or developer
> should read this first. It captures locked decisions, budget rules, the phased build order, and per-phase
> exit criteria ("perfect = done"). The original idea lives in `surgical_video_rag_demo_spec.md`; **this file
> overrides it wherever they conflict**, because it resolves the spec's open gaps.

---

## 0. What we are building (one paragraph)

A **local, demo-only** Surgical Video RAG system for a single laparoscopic cholecystectomy video plus 3–5
trusted guideline documents. It proves 6 things: video understanding, timestamp-based retrieval, medical
document retrieval, grounded answer generation, source evidence, and a basic physician review workflow.
It is an **educational / review tool — NOT diagnostic, NOT treatment guidance.**

---

## 1. Locked decisions (do not re-litigate without updating this file)

| Decision | Choice | Rationale |
|---|---|---|
| Retrieval / embeddings | **OpenAI `text-embedding-3-small` + in-memory NumPy cosine** | No infra, ~30 lines, fully local, cheap |
| Vision model | **Configurable via `.env`, default `gpt-4o-mini`** | Budget-first; flip to `gpt-4o` only if Phase 1 quality is poor |
| Answer model | **`gpt-4o-mini`** (configurable) | Budget-first |
| Vector store | None — NumPy arrays + SQLite metadata | Demo scale is tiny |
| Two-pass sampling | **Coarse pass only for v1.** Fine pass = Phase 7 stretch | Coarse pass alone is enough to demo |
| Timestamp storage | Integer **seconds** everywhere; `fmt_ts()` helper renders `mm:ss` for display | Fixes the spec's seconds-vs-mm:ss mismatch |
| Framework | Plain Python + Streamlit. **No LangChain.** | Keep it debuggable |
| Git | Not initialized unless the user asks | — |

### Budget rules (user is cost-sensitive)
- Default all models to the **mini** tier.
- **Cache every successful API call**; never re-run a processed timestamp.
- Resize frames to **~512px wide** before sending to the vision API.
- Coarse-batch **4–6 frames per vision call**.
- Ingestion must be **resumable** — restart from last unprocessed timestamp.
- Estimated total cost to build + demo the whole thing with mini models: **well under ~$1–2.**

---

## 2. Data shopping list (BLOCKER for Phase 1 — user has none yet)

Drop files here:
```
data/surgery.mp4          # 1 laparoscopic cholecystectomy video
data/papers/*.pdf         # 3–5 trusted guideline documents
```

### Video — options (pick one)
1. **Cholec80 dataset** (CAMMA, Univ. of Strasbourg) — the research-standard lap-chole video set.
   Requires a data-request form / academic license. Best quality + phase labels exist.
2. **IRCAD / WebSurg** — free account, high-quality educational surgical videos.
3. **YouTube educational lap-chole video** — fastest path for a *private, non-redistributed* local demo.
   Download one full-length laparoscopic cholecystectomy. **Do not redistribute; check the video's license.**

> For this private demo we only need ONE video. A single clear full-length lap-chole is enough.

### Documents — target 3–5 (all open-access / authoritative)
1. **SAGES Safe Cholecystectomy** — multi-society consensus / safe-cholecystectomy guidance.
2. **Strasberg — Critical View of Safety (CVS)** — foundational CVS papers (open access).
3. **WSES guidelines — acute calculous cholecystitis** (World Journal of Emergency Surgery, open access).
4. **Tokyo Guidelines (TG18)** — diagnosis/management of acute cholecystitis.
5. *(optional)* A biliary/hepatocystic-triangle **anatomy reference**.

> Prefer surgical-society guidelines and peer-reviewed open-access sources. Avoid blogs.

---

## 3. Repository layout

```
Medical_Video_RAG/
├── app.py                      # Streamlit UI (Phase 5)
├── config.py                   # models, paths, sampling params, env
├── .env / .env.example         # OPENAI_API_KEY (+ optional model overrides)
├── requirements.txt
├── PROJECT_PLAN.md             # <- this file
├── surgical_video_rag_demo_spec.md   # original idea
│
├── pipeline/
│   ├── __init__.py
│   ├── util.py                 # fmt_ts(), parsing helpers   (Phase 0)
│   ├── db.py                   # SQLite init + helpers        (Phase 0)
│   ├── video.py                # FFmpeg sampling              (Phase 1)
│   ├── analyze.py              # OpenAI vision -> observations(Phase 1)
│   ├── documents.py            # PDF -> chunks                (Phase 3)
│   ├── index.py                # embeddings + cosine index    (Phase 2/3)
│   ├── retrieve.py             # search_video / search_documents (Phase 2/3)
│   └── answer.py               # grounded answer generation   (Phase 4)
│
├── models/
│   ├── __init__.py
│   └── schemas.py              # Pydantic models              (Phase 0)
│
├── data/
│   ├── surgery.mp4             # (user-provided)
│   ├── papers/                 # (user-provided PDFs)
│   ├── frames/                 # extracted frames
│   ├── chunks/                 # document chunk cache
│   └── observations.json       # cached vision output
│
├── db/
│   └── demo.db                 # SQLite
│
└── scripts/
    ├── init_db.py
    ├── ingest_video.py         # Phase 1 entrypoint
    └── ingest_documents.py     # Phase 3 entrypoint
```

---

## 4. Surgical phase enum (model must pick from these or `Unknown`)

```
Preparation
Calot triangle dissection
Clipping and cutting
Gallbladder dissection
Gallbladder retraction
Cleaning and coagulation
Gallbladder packaging
Unknown
```

## 5. Vision analysis guardrails
- May describe: visible anatomy, tools, actions, likely phase, transitions, observable events.
- Must NOT invent: surgeon intent, clinical reasoning, diagnosis, patient condition, safety conclusions, treatment.
- If not visually supported: *"Reason cannot be determined from visual evidence alone."*
- Unclear content → `phase = Unknown`. Never hallucinate.
- Validate every response with Pydantic; retry once on failure.

## 6. Answer generation rules
- Answer only from retrieved evidence.
- Separate visual **observation** from document **reference knowledge**.
- Always cite video timestamps; always name the document source.
- No diagnosis, no treatment recommendation.
- If evidence is insufficient, say so.

---

## 7. PHASED BUILD ORDER (complete one, verify exit criteria, then next)

### Phase 0 — Foundation & decisions  *(no data needed)*
- Scaffold repo, `config.py`, `models/schemas.py`, `pipeline/util.py`, `pipeline/db.py`, `scripts/init_db.py`,
  `requirements.txt`, `.env.example`, `README.md`.
- **Exit:** `python scripts/init_db.py` creates `db/demo.db`; all modules import clean; decisions locked here.
- **Status:** IN PROGRESS

### Phase 1 — Video ingestion (coarse pass)  *(the hard/risky phase)*
- `pipeline/video.py`: probe duration/fps/res; extract 1 frame / 20s → `data/frames/frame_SSSSSS.jpg` (seconds).
- `pipeline/analyze.py`: batch 4–6 frames → vision model → validated `VideoObservation` JSON.
- `scripts/ingest_video.py`: resumable, cached to `data/observations.json` + SQLite.
- **Exit:** `data/observations.json` contains several **correctly timestamped, useful** observations; the
  clip-applier / clipping region is captured. Cost stays minimal.
- **Status:** ✅ DONE. 18.2-min video (1280x720@30) → 219 windows (1 fps, 5s windows), 0 validation
  fallbacks. Clipping captured (22 windows, first credible clip ~4:00, clip applier + cystic duct clearly
  described). Intro slides correctly labeled Unknown. Resumable verified (segment-test windows skipped).
  NOTE: window-level phase labels are noisy between visually-similar phases (Calot vs Gallbladder
  dissection) — expected for single-window vision; a smoothing pass is an optional future improvement.

### Phase 2 — Video semantic retrieval
- `pipeline/index.py`: embed each observation's searchable text; store vectors.
- `pipeline/retrieve.py`: `search_video(query, top_k=3)`.
- **Exit:** In terminal, "Where does clipping begin?" returns the correct timestamp.
- **Status:** ✅ DONE. `index.py` (embed all 219 obs, L2-normalized, saved to data/video_index.npy +
  .json) + `retrieve.py` (`search_video`, cosine dot-product, reviewed_only filter) + `scripts/build_index.py`.
  Verified: clipping/clip-applier/Calot queries all return correct windows (Calot sim ~0.59). Edge cases pass
  (empty query, reviewed_only-with-none, top_k>corpus). NOTE: pure semantic search ranks by relevance, not
  time — "begin/first" temporal reasoning is deferred to the Phase 4 answer layer (sort clipping hits by time).

### Phase 3 — Document ingestion + knowledge retrieval
- `pipeline/documents.py`: PDF → text → chunks (with `document_name`, page/section) → embeddings.
- `scripts/ingest_documents.py`; extend `retrieve.py` with `search_documents(query, top_k=3)`.
- **Exit:** "What is the Critical View of Safety?" returns relevant document chunks with source.
- **Status:** ✅ DONE. Research agent sourced 5 verified open-access PDFs (WSES BDI 2020, CVS/Frontiers,
  WSES acute cholecystitis 2020, Tokyo Guidelines criteria, BDI/cholangiography); verification agent
  confirmed all text-extractable + on-topic. `documents.py` (word-aware chunking, page-tagged) → 467 chunks;
  `index.build_document_index` (batched embeddings, DOC_EMB/DOC_META + SQLite mirror); `retrieve.search_documents`.
  Verified: CVS + "verify before clipping" (→ CVS 3 steps, 0.62) + BDI-prevention queries all relevant.
  Edge cases pass. NOTE: reference/bibliography pages get chunked too and can rank on keyword-dense queries —
  minor, acceptable for demo (could filter later).

### Phase 4 — Combined grounded RAG (terminal)
- `pipeline/answer.py`: takes query + video_results + document_results → grounded answer per Section 6 rules.
- Modes: Video / Knowledge / Combined (Combined is default).
- **Exit:** Main demo query returns video evidence + document evidence + grounded answer **in the terminal**.
- **Status:** ✅ DONE. `answer.py`: 3 modes; grounded prompt (separates video-observation vs doc-reference,
  cites timestamps + doc sources, refuses diagnosis/treatment/intent/patient-management, says-when-insufficient).
  KEY: two-agent design debate → deterministic TEMPORAL ANCHOR (exact argmin/argmax over start_sec per mapped
  phase) makes "where does clipping begin?" correctly answer 4:00; non-destructive, inert when intent/phase
  don't map. Neutral "when" doesn't override strong "end" signal (bug fixed). Adversarial red-team agent:
  8/8 PASS (diagnosis/treatment/intent/injection/false-premise/out-of-range all refused, no fabrication);
  one low-severity management-drift finding fixed by prompt hardening + re-verified. Marquee combined query:
  "clipping begins 4:00" + CVS 3-criteria from guideline, cited.

### Phase 5 — Streamlit UI + timestamp navigation
- `app.py`: video player, question box, 3 mode radio, answer, video evidence, document evidence.
- Jump-to-timestamp via `st.video(path, start_time=start_sec)`.
- **Exit:** All 5 demo queries work in-browser; clicking a video result seeks the player.
- **Status:** ✅ DONE. `app.py`: player with `st.video(start_time=seek)` jump-to-timestamp, question box,
  3-mode radio, reviewed-only checkbox, grounded answer, video + document evidence panels, safety footer.
  Answers cached in session_state (jump/review reruns never re-call the LLM). Verified headless via Streamlit
  AppTest (render + Jump→seek=240 + no exceptions). Code-review agent findings H1/M2/M3/L7/L8 all fixed +
  re-verified.

### Phase 6 — Physician review + reviewed-only mode  *(= Definition of Done)*
- Approve / Edit / Reject per observation → `review_status` (+ `reviewed_text` on edit).
- "Reviewed knowledge only" toggle → retrieval filtered to `review_status IN ('approved','edited')`.
- **Exit:** Full loop AI-proposes → human-validates → trusted-retrieval works.
- **Status:** ✅ DONE. `db.update_review` (validated status transitions), `get_reviewed_start_secs` (live),
  inline Approve/Edit/Reject in the UI. `search_video(reviewed_only=True)` reads review state LIVE from DB
  so approve/reject apply instantly without re-embedding (edited-text search needs a rebuild — noted in UI).
  Verified: approve→appears in reviewed-only search & card badge updates; reject→drops; invalid status guarded.

### Phase 7 — Two-pass fine sampling  *(stretch, only if time)*
- Fine 1 frame / 5s on regions flagged `important` (Calot, CVS, clipping, low-confidence transitions).
- **Exit:** Sharper timestamps around key regions without re-processing the whole video.
- **Status:** ⊘ N/A (superseded). The video was sampled at 1 fps (1s) across the WHOLE video — already 5×
  finer than this phase's planned 5s "fine pass", so a coarse→fine second pass would add code that does LESS
  than we already have. Only a SUB-second pass (e.g. 2 fps on `important` regions) would go finer; deemed
  overkill for the demo. Revisit only if second-level precision on a specific event is ever required.

### Phase 8 — Lightweight GraphRAG (ADDITIVE layer)  *(user-requested; after core demo)*
Vector RAG stays the primary retriever; the graph AUGMENTS it and falls back to vector cleanly.
- **Self-contained approach (honors all constraints):** custom OpenAI structured-output extraction of typed
  triples over the doc chunks + video observations, constrained to a small surgical ontology
  (anatomy, instrument, phase, action, complication, safety-step). Store in `networkx` (pure-Python,
  in-venv), persist to `data/graph.json`. NO Neo4j / Microsoft GraphRAG / LangChain / Docling (all violate
  the lightweight + self-contained + no-infra rules).
- **Use:** at query time, match query entities → pull neighborhood subgraph as extra structured evidence
  appended to the answer context; visualize the graph in the Streamlit UI. If graph adds nothing, fall back
  to vector (never worse than vector-only).
- **Exit:** graph built from docs+video; a multi-hop query (e.g. "what must be verified before clipping")
  surfaces CVS→criteria via the graph; graph visible in UI; vector fallback intact.
- **Status:** ✅ DONE. Two-agent design debate → functional unified GraphRAG with A-as-fallback.
  `pipeline/graph.py`: closed canonical ontology (38 nodes) + seeded authoritative backbone (12 edges) +
  DETERMINISTIC video↔concept edges from the 219 observations (19 edges, with timestamps) + LLM-extracted,
  type-validated document edges (cached). `scripts/build_graph.py`. Additive integration in `answer.py`
  (subgraph injected as NON-CITABLE hints; silent fallback to vector when no entity match). UI: Graphviz
  visualization panel (black=backbone, blue=doc, green=video). Adversarial red-team agent: 5/6 → found
  entity-match-before-'?' bug + graph-citation drift + extraction noise; ALL fixed (regex word-boundary
  matching, non-citable relabel + prompt hardening, type-validation + reverse-dup drop) and re-verified.
  Flagship: "what to verify before clipping" → CVS → 3 criteria; fallback + safety intact.

---

## 8. Definition of Done (from spec §33)
- [ ] video processed  [ ] timestamped observations generated  [ ] observations cached
- [ ] video semantic search  [ ] documents searchable  [ ] combined retrieval
- [ ] answers cite timestamps  [ ] answers name document evidence
- [ ] Streamlit jumps to timestamp  [ ] approve/edit/reject  [ ] reviewed-only mode
- [ ] main combined demo query works reliably

## 9. The 5 demo queries (test set)
1. "Where does clipping begin?" → video timestamp
2. "Show moments where a clip applier is being used." → multiple timestamps
3. "Show the Calot triangle dissection section." → correct region
4. "What is the Critical View of Safety?" → document answer
5. **"Show where clipping begins and explain what should be verified before clipping."** → combined (headline demo)

## 10. Guiding rule
When forced to choose between **better architecture** and a **working demo → choose the working demo.**
No infra/abstractions unless they unblock something immediate. Success metric: *a user asks a surgical
question and immediately gets a relevant video timestamp + trusted medical knowledge with visible evidence.*

## 11. Safety footer (must appear in UI)
```
Demo for surgical education, review, and information retrieval.
AI-generated video observations require expert validation.
Not intended for diagnosis or treatment decisions.
```
