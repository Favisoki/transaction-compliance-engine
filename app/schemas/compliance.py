"""Manual review schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import ReviewDecision


class TransactionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    reviewer: str = Field(min_length=2, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("reviewer")
    @classmethod
    def _strip_reviewer(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("reviewer must contain at least two non-space characters")
        return stripped

    @field_validator("notes")
    @classmethod
    def _strip_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        notes = value.strip()
        return notes or None
