"""Transaction request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import Currency, Severity, TransactionStatus
from app.schemas.user import UserSummary


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Currency = Currency.USD
    description: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _parties_must_differ(self) -> TransactionCreate:
        if self.sender_id == self.receiver_id:
            raise ValueError("sender_id and receiver_id must be different users")
        return self

    @model_validator(mode="after")
    def _normalise_description(self) -> TransactionCreate:
        if self.description is not None:
            self.description = self.description.strip()
            if not self.description:
                raise ValueError("description must not be blank when provided")
        return self


class TransactionAccepted(BaseModel):
    """Fast acknowledgement returned after persisting and enqueueing."""

    transaction_id: uuid.UUID
    status: TransactionStatus
    replayed: bool = False
    message: str = "Transaction accepted for compliance review"


class ComplianceLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_code: str
    rule_name: str
    severity: Severity
    message: str
    details: dict[str, Any]
    created_at: datetime


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    amount: Decimal
    currency: Currency
    description: str | None
    status: TransactionStatus
    created_at: datetime
    updated_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None


class TransactionDetail(TransactionRead):
    sender: UserSummary
    receiver: UserSummary
    compliance_logs: list[ComplianceLogRead] = Field(default_factory=list)


class FlaggedTransactionPage(BaseModel):
    items: list[TransactionDetail]
    total: int
    limit: int
    offset: int
