"""User request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import normalize_country_code, normalize_email


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    country_code: str = Field(min_length=2, max_length=2)
    risk_score: int = Field(default=0, ge=0, le=100)
    kyc_verified: bool = False

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: EmailStr) -> str:
        return normalize_email(str(value))

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("full_name must not be blank")
        return stripped

    @field_validator("country_code")
    @classmethod
    def _normalise_country(cls, value: str) -> str:
        return normalize_country_code(value)


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    country_code: str
    risk_score: int
    kyc_verified: bool


class UserRead(UserSummary):
    full_name: str
    created_at: datetime
    updated_at: datetime
