# Surgical Video RAG Demo — Development Specification

## 1. Goal

Build a **working demo in 1–2 days** for a surgical-video RAG system using:

- 1 laparoscopic cholecystectomy video
- 3–5 trusted medical documents/guidelines
- OpenAI API
- MacBook
- Python + Streamlit
- Local lightweight storage

The demo must prove that the system can combine:

1. **Video understanding**
2. **Timestamp-based retrieval**
3. **Medical document knowledge retrieval**
4. **Grounded answer generation**
5. **Source evidence**
6. **Basic physician review workflow**

The system is a **demo / educational / review tool**, not a diagnostic or treatment recommendation system.

---

# 2. Core Demo Experience

The final demo should support these flows.

## A. Video-only retrieval

User asks:

> Where does clipping begin?

System returns:

- answer
- relevant timestamp
- short visual observation
- clickable result that jumps the video player to that timestamp

Example:

```text
Clipping begins around 18:42.

Evidence:
18:42–18:57
Phase: Clipping and cutting
Observation: Clip applier is visible and clip application begins.
```

---

## B. Knowledge-only retrieval

User asks:

> What should be verified before clipping?

System retrieves trusted medical literature/guidelines and generates a grounded answer with document sources.

---

## C. Combined retrieval

This is the main demo.

User asks:

> Show where clipping begins and explain what should be verified before clipping.

Pipeline:

```text
Question
   |
   +--> Video Retrieval
   |       |
   |       +--> relevant timestamped observations
   |
   +--> Medical Knowledge Retrieval
           |
           +--> relevant guideline/document chunks

                |
                v

          Grounded GPT Answer
                |
                v

     Answer + Video Evidence + Document Evidence
```

---

# 3. Fixed Procedure

Use:

**Laparoscopic cholecystectomy**

Reasons:

- clear procedural phases
- good public/open surgical-video ecosystem
- strong guideline material
- mature research datasets
- easy to demonstrate clipping, dissection, tool use, and Critical View of Safety

---

# 4. Scope Constraints

This is a fast demo.

## DO build

- one surgery video
- timestamped frame extraction
- AI visual observations
- procedural phase candidates
- instruments/actions candidates
- medical document ingestion
- semantic retrieval
- combined video + document RAG
- timestamp evidence
- simple physician approve/edit/reject flow
- Streamlit UI

## DO NOT build

- model training
- fine-tuning
- real-time intraoperative AI
- diagnosis
- treatment decision making
- surgical outcome prediction
- automated skill scoring
- SAM / segmentation unless everything else is complete
- SurgVLP integration in v1
- Qdrant/Postgres/Kubernetes
- multi-agent frameworks
- complex knowledge graphs
- hospital/EHR/PACS integrations
- production authentication
- production compliance architecture
- large-scale ingestion

---

# 5. Technology Stack

Keep the stack minimal.

```text
Python 3.11+
Streamlit
OpenAI Python SDK
FFmpeg
SQLite
Pydantic
python-dotenv
```

Optional:

```text
PyMuPDF or pypdf
```

Only use PDF extraction manually if hosted OpenAI document/vector-store ingestion becomes inconvenient.

Avoid LangChain unless it removes meaningful code.

---

# 6. High-Level Architecture

```text
                         SURGERY VIDEO
                               |
                               v
                         FFmpeg Sampling
                               |
                               v
                    Timestamped Frames/Windows
                               |
                               v
                     OpenAI Vision Analysis
                               |
                               v
                 Structured Surgical Observations
                               |
                    +----------+----------+
                    |                     |
                    v                     v
               Local SQLite        Video Retrieval Index
                    |                     |
                    |                     |
                    |              +------+
                    |              |
                    |              |
TRUSTED DOCUMENTS   |              |
       |            |              |
       v            |              |
Document Ingestion  |              |
       |            |              |
       v            |              |
Knowledge Retrieval Index          |
       |                            |
       +--------------+-------------+
                      |
                      v
                 User Question
                      |
           +----------+----------+
           |                     |
           v                     v
      Video Search          Knowledge Search
           |                     |
           +----------+----------+
                      |
                      v
              Grounded GPT Answer
                      |
                      v
          Answer + Timestamp + Sources
```

---

# 7. Repository Structure

Create:

```text
surgical-rag-demo/
│
├── app.py
├── .env
├── .env.example
├── requirements.txt
├── README.md
│
├── pipeline/
│   ├── __init__.py
│   ├── video.py
│   ├── analyze.py
│   ├── documents.py
│   ├── index.py
│   ├── retrieve.py
│   └── answer.py
│
├── models/
│   ├── __init__.py
│   └── schemas.py
│
├── data/
│   ├── surgery.mp4
│   ├── papers/
│   ├── frames/
│   ├── chunks/
│   └── observations.json
│
├── db/
│   └── demo.db
│
└── scripts/
    ├── ingest_video.py
    └── ingest_documents.py
```

---

# 8. Environment Variables

`.env`

```env
OPENAI_API_KEY=...
```

`.env.example`

```env
OPENAI_API_KEY=your_key_here
```

Never commit the real API key.

---

# 9. Phase 1 — Video Preprocessing

File:

```text
pipeline/video.py
```

Responsibilities:

1. inspect video
2. get:
   - duration
   - FPS
   - resolution
3. extract timestamped frames
4. save frames with timestamps in filenames

Example:

```text
data/frames/
    frame_000000.jpg
    frame_000020.jpg
    frame_000040.jpg
```

Where filename represents seconds.

Use FFmpeg.

---

# 10. Two-Pass Video Sampling Strategy

Do NOT analyze every frame.

## Pass 1 — Coarse

Sample approximately:

```text
1 frame every 20 seconds
```

For a 60-minute surgery:

```text
~180 frames
```

Analyze frames in small temporal groups.

Suggested input window:

```text
4–6 sequential frames
```

The model should infer:

- likely procedural phase
- visible instruments
- visible action
- short observation
- whether the segment looks important
- confidence

---

## Pass 2 — Fine

For important regions, sample approximately:

```text
1 frame every 5 seconds
```

Fine analysis should be triggered around:

- Calot triangle dissection
- Critical View of Safety region
- clipping/cutting
- unusual events
- low-confidence phase transitions

Do not fine-sample the entire video unless necessary.

---

# 11. Surgical Phase Labels

Restrict model output to:

```text
Preparation
Calot triangle dissection
Clipping and cutting
Gallbladder dissection
Gallbladder retraction
Cleaning and coagulation
Gallbladder packaging
Unknown
```

The model should choose `Unknown` instead of inventing a phase.

---

# 12. Structured Video Observation Schema

Use Pydantic.

File:

```text
models/schemas.py
```

Suggested model:

```python
from pydantic import BaseModel
from typing import List, Optional

class VideoObservation(BaseModel):
    start_sec: int
    end_sec: int

    phase: str

    instruments: List[str]
    actions: List[str]

    observation: str

    confidence: float

    important: bool = False

    review_status: str = "unreviewed"
    reviewed_text: Optional[str] = None
```

Possible review values:

```text
unreviewed
approved
edited
rejected
```

---

# 13. Vision Analysis Rules

File:

```text
pipeline/analyze.py
```

Use OpenAI vision-capable model.

The prompt must be conservative.

The model may describe:

- visible anatomy
- visible tools
- visible actions
- likely surgical phase
- transitions
- observable events

The model must NOT invent:

- surgeon intent
- clinical reasoning
- diagnosis
- patient condition
- safety conclusions
- treatment recommendations

Bad:

```text
The surgeon changed instruments because tissue tension was unsafe.
```

Good:

```text
The surgeon changes from one instrument to another at approximately 21:14.
```

If reasoning is not visually supported, say:

```text
Reason cannot be determined from visual evidence alone.
```

---

# 14. Vision Analysis Output

Each request should return structured JSON.

Example:

```json
{
  "start_sec": 1080,
  "end_sec": 1100,
  "phase": "Calot triangle dissection",
  "instruments": [
    "grasper",
    "hook"
  ],
  "actions": [
    "retraction",
    "dissection"
  ],
  "observation": "Dissection is visible in the hepatocystic triangle while tissue is retracted.",
  "confidence": 0.86,
  "important": true
}
```

Validate every model response with Pydantic.

Retry once on validation failure.

---

# 15. Local Database

Use SQLite.

Table:

```sql
CREATE TABLE video_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    start_sec INTEGER NOT NULL,
    end_sec INTEGER NOT NULL,

    phase TEXT,
    instruments TEXT,
    actions TEXT,

    observation TEXT NOT NULL,

    confidence REAL,

    important INTEGER DEFAULT 0,

    review_status TEXT DEFAULT 'unreviewed',
    reviewed_text TEXT
);
```

For demo simplicity:

- store list fields as JSON strings
- SQLite is enough

---

# 16. Video Retrieval Representation

For each video observation, generate searchable text such as:

```text
Procedure: Laparoscopic cholecystectomy

Timestamp: 18:00–18:20

Phase: Calot triangle dissection

Instruments:
grasper, hook

Actions:
dissection, retraction

Observation:
Dissection is visible in the hepatocystic triangle while tissue is retracted.
```

Include metadata:

```json
{
  "source_type": "video",
  "start_sec": 1080,
  "end_sec": 1100,
  "phase": "Calot triangle dissection",
  "review_status": "unreviewed"
}
```

---

# 17. Medical Knowledge Corpus

Start with only:

```text
3–5 trusted documents
```

Target content:

1. laparoscopic cholecystectomy technique
2. Critical View of Safety
3. safe cholecystectomy guideline
4. complications / bile duct injury prevention
5. optional anatomy reference

Documents go in:

```text
data/papers/
```

The demo should prefer:

- professional surgical society guidelines
- peer-reviewed open-access publications
- authoritative surgical references

Avoid random blogs.

---

# 18. Knowledge Retrieval Representation

Every document chunk needs:

```text
source_type = document
document_name
section/page if available
chunk_text
```

Example:

```json
{
  "source_type": "document",
  "document_name": "safe_cholecystectomy_guideline.pdf",
  "page": 8,
  "section": "Critical View of Safety"
}
```

---

# 19. Retrieval Strategy

Keep video retrieval and document retrieval logically separate.

Do NOT rely on one unconstrained agent call.

For every user query:

```python
video_results = search_video(query, top_k=3)

document_results = search_documents(query, top_k=3)

answer = generate_grounded_answer(
    query=query,
    video_results=video_results,
    document_results=document_results,
)
```

This makes debugging easy.

---

# 20. Retrieval Modes

Support 3 modes.

## Mode 1 — Video

Search only video observations.

Example:

```text
Where does clipping begin?
```

---

## Mode 2 — Knowledge

Search only documents.

Example:

```text
What is the Critical View of Safety?
```

---

## Mode 3 — Combined

Search both.

Example:

```text
Show where clipping begins and explain what should be verified before clipping.
```

This is the default demo mode.

---

# 21. Grounded Answer Generation

File:

```text
pipeline/answer.py
```

The final model receives:

```text
USER QUESTION

VIDEO EVIDENCE

DOCUMENT EVIDENCE
```

Rules:

- answer only from retrieved evidence
- distinguish observation from medical reference knowledge
- do not claim visual certainty if evidence is unclear
- no diagnosis
- no treatment recommendation
- always cite video timestamps
- always identify document source when used
- if evidence is insufficient, say so

Example result:

```text
The clipping sequence appears to begin at approximately 18:42.

Video evidence:
18:42–18:57 — A clip applier is visible and clip application begins.

Reference knowledge:
The retrieved safe-cholecystectomy guideline describes the structures that should be verified before division.

This answer combines an AI-generated visual observation with retrieved reference material.
```

---

# 22. Physician Review Workflow

Keep this simple.

For each video observation show:

```text
AI Observation

Timestamp:
18:42–18:57

Phase:
Clipping and cutting

Observation:
Clip application begins.

[Approve] [Edit] [Reject]
```

Actions:

## Approve

```text
review_status = approved
```

## Edit

Save:

```text
review_status = edited
reviewed_text = physician edited text
```

## Reject

```text
review_status = rejected
```

---

# 23. Reviewed-Only Search

Optional but strongly recommended.

Add:

```text
[ ] Reviewed knowledge only
```

When enabled:

```text
review_status IN ('approved', 'edited')
```

This demonstrates:

```text
AI proposes
      ↓
Human validates
      ↓
Trusted knowledge
      ↓
Retrieval
```

---

# 24. Streamlit UI

File:

```text
app.py
```

Do NOT overdesign.

One page is enough.

Suggested layout:

```text
------------------------------------------------

SURGICAL VIDEO RAG DEMO

------------------------------------------------

[ VIDEO PLAYER ]

Current Case:
Laparoscopic Cholecystectomy

------------------------------------------------

Ask this surgery

[________________________________________]

Mode:
(o) Combined
( ) Video
( ) Knowledge

[ Ask ]

------------------------------------------------

ANSWER

...

------------------------------------------------

VIDEO EVIDENCE

▶ 18:42–18:57
Clipping and cutting
Clip application begins.

[Jump to timestamp]

------------------------------------------------

DOCUMENT EVIDENCE

Safe Cholecystectomy Guideline
Critical View of Safety
...

------------------------------------------------
```

---

# 25. Timestamp Navigation

Clicking a video result must seek the video to:

```text
start_sec
```

This is one of the most important demo interactions.

If direct in-player seeking becomes difficult, re-render the Streamlit video player with:

```python
st.video(video_path, start_time=start_sec)
```

That is sufficient for the demo.

---

# 26. Main Demo Questions

Hard-code / prepare these queries for testing.

## Query 1

```text
Where does clipping begin?
```

Expected:

- video timestamp

---

## Query 2

```text
Show moments where a clip applier is being used.
```

Expected:

- multiple timestamps

---

## Query 3

```text
Show the Calot triangle dissection section.
```

Expected:

- correct procedure region

---

## Query 4

```text
What is the Critical View of Safety?
```

Expected:

- medical document answer

---

## Query 5 — Main Demo Query

```text
Show where clipping begins and explain what should be verified before clipping.
```

Expected:

```text
video evidence
+
guideline evidence
+
grounded combined answer
```

---

# 27. Development Order

DO NOT build everything simultaneously.

## Milestone 1 — Video ingestion

Must work first.

```text
surgery.mp4
    |
    v
FFmpeg
    |
    v
20-second frames
    |
    v
OpenAI Vision
    |
    v
Valid observations.json
```

Success condition:

At least several clearly useful, correctly timestamped surgical observations exist.

---

## Milestone 2 — Video semantic retrieval

Question:

```text
Where does clipping begin?
```

must return a relevant timestamp.

No UI required yet.

---

## Milestone 3 — Document ingestion

Load 3–5 trusted documents.

Question:

```text
What is the Critical View of Safety?
```

must return relevant document evidence.

---

## Milestone 4 — Combined retrieval

Question:

```text
Show where clipping begins and explain what should be verified before clipping.
```

must retrieve both:

```text
video evidence
+
document evidence
```

---

## Milestone 5 — Streamlit UI

Only after retrieval works.

Add:

- video player
- question box
- modes
- answer
- evidence
- timestamp navigation

---

## Milestone 6 — Physician review

Add:

- approve
- edit
- reject
- reviewed-only toggle

---

# 28. Recommended Development Schedule

## First development block

Focus only on:

```text
video.py
analyze.py
schemas.py
```

Goal:

```text
surgery.mp4
→ observations.json
```

---

## Second development block

Focus on:

```text
documents.py
index.py
retrieve.py
answer.py
```

Goal:

```text
combined RAG working in terminal
```

---

## Final development block

Focus on:

```text
app.py
```

Goal:

```text
demo-ready Streamlit app
```

---

# 29. Cost / API Control

Because the video may be long:

- do not upload/analyze every frame
- resize frames before API requests
- use coarse sampling first
- batch neighboring frames logically
- cache every successful model result
- never re-run processed timestamps unless explicitly requested
- save intermediate JSON after every successful analysis
- fine-analyze only important regions

The ingestion script must be resumable.

If execution stops halfway, restart from the last unprocessed timestamp.

---

# 30. Error Handling

Implement simple resilience.

For every API call:

- catch API errors
- retry with exponential backoff
- maximum 2–3 retries
- save progress continuously

For invalid JSON:

- validate with Pydantic
- retry once

For unknown visual content:

```text
phase = Unknown
```

Do not hallucinate.

---

# 31. Cache Strategy

Create:

```text
data/observations.json
```

Example:

```json
[
  {
    "start_sec": 1080,
    "end_sec": 1100,
    "phase": "Calot triangle dissection",
    "instruments": ["grasper", "hook"],
    "actions": ["retraction", "dissection"],
    "observation": "Dissection is visible while tissue is retracted.",
    "confidence": 0.86,
    "important": true,
    "review_status": "unreviewed",
    "reviewed_text": null
  }
]
```

Before analyzing a timestamp, check whether it already exists.

---

# 32. Safety / Language Requirement

This demo is NOT:

- diagnostic AI
- autonomous surgical guidance
- treatment recommendation system

UI footer:

```text
Demo for surgical education, review, and information retrieval.
AI-generated video observations require expert validation.
Not intended for diagnosis or treatment decisions.
```

---

# 33. Definition of Done

The demo is complete when all of these work:

- [ ] surgery video can be processed
- [ ] timestamped frame observations are generated
- [ ] observations are cached locally
- [ ] user can search video semantically
- [ ] trusted documents are searchable
- [ ] combined video + document retrieval works
- [ ] answers contain timestamp evidence
- [ ] answers identify document evidence
- [ ] Streamlit video can jump to result timestamp
- [ ] physician can approve/edit/reject an observation
- [ ] reviewed-only mode works
- [ ] main combined demo query works reliably

---

# 34. Priority Rule for Claude Code

When choosing between:

```text
better architecture
```

and

```text
working demo
```

always choose:

```text
WORKING DEMO
```

Do not introduce infrastructure or abstractions unless they solve an immediate blocker.

The primary success metric is:

> Can a user ask a surgical question and immediately get a relevant video timestamp plus trusted medical knowledge with visible evidence?

If yes, the demo is successful.

---

# 35. First Task to Implement

Start here.

Implement:

```text
pipeline/video.py
pipeline/analyze.py
models/schemas.py
scripts/ingest_video.py
```

Required first command:

```bash
python scripts/ingest_video.py
```

Expected result:

```text
data/observations.json
```

containing valid timestamped surgical observations.

Do not start Streamlit UI until this works.
