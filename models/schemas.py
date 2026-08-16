"""Pydantic data contracts. Every AI response is validated against these."""
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

import config


class VideoObservation(BaseModel):
    """One timestamped surgical observation produced by vision analysis."""

    start_sec: int
    end_sec: int

    phase: str  # must be one of config.PHASES

    instruments: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)

    observation: str

    confidence: float = 0.0

    important: bool = False

    review_status: str = "unreviewed"  # unreviewed | approved | edited | rejected
    reviewed_text: Optional[str] = None

    @field_validator("phase", mode="before")
    @classmethod
    def _valid_phase(cls, v) -> str:
        # Runs before type coercion so null / non-str / unexpected values all map to
        # "Unknown" rather than inventing a phase or raising.
        return v if isinstance(v, str) and v in config.PHASES else "Unknown"

    @field_validator("instruments", "actions", mode="before")
    @classmethod
    def _coerce_str_list(cls, v):
        # Model may return null, a single string, or a proper list.
        if v is None:
            return []
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",")]
            return [p for p in parts if p]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("observation", mode="before")
    @classmethod
    def _observation_str(cls, v) -> str:
        return v if isinstance(v, str) and v.strip() else "No observation provided."


class DocumentChunk(BaseModel):
    """One retrievable chunk of a trusted medical document."""

    source_type: str = "document"
    document_name: str
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_text: str
