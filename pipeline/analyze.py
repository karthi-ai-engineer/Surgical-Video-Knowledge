"""Phase 1b: send a window of frames to the vision model and return a validated
VideoObservation. Conservative prompt: describe only what's visible, never invent."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import List

from openai import OpenAI
from pydantic import ValidationError

import config
from models.schemas import VideoObservation
from pipeline.video import frame_path

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set (put it in .env).")
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _encode(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/jpeg;base64,{b64}"


SYSTEM_PROMPT = f"""You are a conservative surgical video annotator for a laparoscopic \
cholecystectomy. You are shown a short window of sequential frames (a few seconds apart).

Describe ONLY what is visually present. You MAY report: visible anatomy, visible instruments, \
visible actions, the most likely surgical phase, transitions, and observable events.

You MUST NOT invent: surgeon intent, clinical reasoning, diagnosis, patient condition, safety \
conclusions, or treatment recommendations. If something is not visually supported, do not state it.

The surgical phase MUST be exactly one of:
{chr(10).join('- ' + p for p in config.PHASES)}

If the frames are unclear or do not fit a phase, use "Unknown". Never invent a phase.

Return ONLY a JSON object with these keys:
{{
  "phase": one of the phases above,
  "instruments": [strings],   // visible instruments, e.g. "grasper", "hook", "clip applier"
  "actions": [strings],       // visible actions, e.g. "dissection", "retraction", "clipping"
  "observation": string,      // 1-2 sentences, purely descriptive
  "confidence": number,       // 0.0-1.0, your confidence in the phase label
  "important": boolean        // true if this window shows a key event (clipping, CVS, dissection, unusual event)
}}"""


def _messages(frames: List[int]):
    content = [{
        "type": "text",
        "text": (f"Window: {frames[0]}s to {frames[-1]}s "
                 f"({len(frames)} frames, ~{config.COARSE_INTERVAL_SEC}s apart). "
                 "Analyze and return the JSON object."),
    }]
    for sec in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": _encode(frame_path(sec)), "detail": "low"},
        })
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _call_model(messages, max_api_retries: int = 3) -> str:
    """One chat completion with exponential backoff on API errors."""
    delay = 1.0
    last_err = None
    for _ in range(max_api_retries):
        try:
            resp = get_client().chat.completions.create(
                model=config.VISION_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            return resp.choices[0].message.content
        except Exception as e:  # network / rate limit / transient
            last_err = e
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"Vision API failed after {max_api_retries} retries: {last_err}")


def analyze_window(frames: List[int]) -> VideoObservation:
    """Analyze a window of frame-seconds -> validated VideoObservation.
    Retries once on JSON/validation failure, then falls back to an Unknown stub."""
    start_sec, end_sec = frames[0], frames[-1]
    messages = _messages(frames)

    for attempt in range(2):  # validate + retry once
        raw = _call_model(messages)
        try:
            data = json.loads(raw)
            data["start_sec"] = start_sec
            data["end_sec"] = end_sec
            return VideoObservation(**data)
        except (json.JSONDecodeError, ValidationError, TypeError):
            if attempt == 0:
                messages = messages + [{
                    "role": "user",
                    "content": "Your previous reply was not valid JSON in the required shape. "
                               "Return ONLY the JSON object with the exact keys.",
                }]
                continue

    # Give up gracefully rather than crash the whole ingestion run.
    return VideoObservation(
        start_sec=start_sec, end_sec=end_sec, phase="Unknown",
        instruments=[], actions=[],
        observation="Could not produce a validated observation for this window.",
        confidence=0.0, important=False,
    )
