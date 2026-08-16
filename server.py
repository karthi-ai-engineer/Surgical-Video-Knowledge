"""FastAPI backend for the Surgical Video RAG web UI.

Reuses the existing pipeline (retrieval + grounded answer + graph). Serves the video via
StaticFiles (HTTP range requests -> smooth seeking) and a small JSON API for the frontend.

Run:  ./.venv/bin/python server.py   (then open http://127.0.0.1:8000)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

import config
from pipeline.answer import generate_answer
from pipeline.db import get_conn, update_review, review_counts

app = FastAPI(title="Surgical Video RAG")
WEB = Path(__file__).parent / "web"


class NoCacheStatic(BaseHTTPMiddleware):
    """Never let the browser cache the UI assets during development."""
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/":
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp


app.add_middleware(NoCacheStatic)


class AskReq(BaseModel):
    query: str
    mode: str = "combined"
    reviewed_only: bool = False


class ReviewReq(BaseModel):
    id: int
    status: str
    reviewed_text: Optional[str] = None


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/meta")
def meta():
    dur = 0.0
    try:
        from pipeline.video import probe_video
        dur = probe_video().duration_sec
    except Exception:
        pass
    return {"procedure": config.PROCEDURE, "duration": dur,
            "video_url": "/media/surgery.mp4",
            "has_video": config.VIDEO_PATH.exists()}


@app.get("/api/observations")
def observations():
    """All (non-rejected) observations, sorted by time — drives the live 'Now showing' panel
    and the phase timeline strip."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id,start_sec,end_sec,phase,instruments,observation,confidence,review_status "
            "FROM video_observations WHERE review_status != 'rejected' ORDER BY start_sec"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["instruments"] = json.loads(d["instruments"] or "[]")
        if d.get("review_status") == "edited":
            # reviewed text isn't selected above; keep observation as-is for the panel
            pass
        out.append(d)
    return out


@app.post("/api/ask")
def ask(req: AskReq):
    res = generate_answer(req.query, mode=req.mode, reviewed_only=req.reviewed_only)
    return res


@app.post("/api/review")
def review(req: ReviewReq):
    update_review(req.id, req.status, req.reviewed_text)
    return {"ok": True, "counts": review_counts()}


# Static + media mounts (media supports HTTP range requests for video seeking)
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
app.mount("/media", StaticFiles(directory=str(config.DATA_DIR)), name="media")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
