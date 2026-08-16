"""Local SQLite storage. Demo-scale: list fields stored as JSON strings."""
from __future__ import annotations

import json
import sqlite3
from typing import List

import config
from models.schemas import VideoObservation

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_sec INTEGER NOT NULL,
    end_sec INTEGER NOT NULL,
    phase TEXT,
    instruments TEXT,        -- JSON array string
    actions TEXT,            -- JSON array string
    observation TEXT NOT NULL,
    confidence REAL,
    important INTEGER DEFAULT 0,
    review_status TEXT DEFAULT 'unreviewed',
    reviewed_text TEXT
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_name TEXT NOT NULL,
    page INTEGER,
    section TEXT,
    chunk_text TEXT NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_observation(conn: sqlite3.Connection, obs: VideoObservation) -> int:
    cur = conn.execute(
        """INSERT INTO video_observations
           (start_sec, end_sec, phase, instruments, actions, observation,
            confidence, important, review_status, reviewed_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            obs.start_sec, obs.end_sec, obs.phase,
            json.dumps(obs.instruments), json.dumps(obs.actions),
            obs.observation, obs.confidence, int(obs.important),
            obs.review_status, obs.reviewed_text,
        ),
    )
    return cur.lastrowid


def load_observations(conn: sqlite3.Connection, reviewed_only: bool = False) -> List[dict]:
    q = "SELECT * FROM video_observations"
    if reviewed_only:
        q += " WHERE review_status IN ('approved', 'edited')"
    q += " ORDER BY start_sec"
    rows = conn.execute(q).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["instruments"] = json.loads(d["instruments"] or "[]")
        d["actions"] = json.loads(d["actions"] or "[]")
        out.append(d)
    return out


def update_review(obs_id: int, status: str, reviewed_text: str | None = None) -> None:
    """Set an observation's review status (approved | edited | rejected | unreviewed).
    reviewed_text is stored only for 'edited'."""
    if status not in ("approved", "edited", "rejected", "unreviewed"):
        raise ValueError(f"invalid review status: {status}")
    text = reviewed_text if status == "edited" else None
    with get_conn() as conn:
        conn.execute(
            "UPDATE video_observations SET review_status = ?, reviewed_text = ? WHERE id = ?",
            (status, text, obs_id),
        )
        conn.commit()


def get_reviewed_start_secs() -> set:
    """Live set of start_sec for observations approved/edited — used for reviewed-only
    retrieval so approve/reject reflects immediately without rebuilding the index."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT start_sec FROM video_observations "
            "WHERE review_status IN ('approved','edited')"
        ).fetchall()
    return {r["start_sec"] for r in rows}


def review_counts() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT review_status, COUNT(*) c FROM video_observations GROUP BY review_status"
        ).fetchall()
    return {r["review_status"]: r["c"] for r in rows}


def replace_document_chunks(chunks) -> int:
    """Clear and repopulate the document_chunks table from a list of DocumentChunk.
    Chunks are derived from the PDFs, so a full replace on rebuild is correct."""
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM document_chunks")
        conn.executemany(
            "INSERT INTO document_chunks (document_name, page, section, chunk_text) "
            "VALUES (?, ?, ?, ?)",
            [(c.document_name, c.page, c.section, c.chunk_text) for c in chunks],
        )
        conn.commit()
    return len(chunks)


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {config.DB_PATH}")
