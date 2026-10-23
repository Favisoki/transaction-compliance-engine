from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import TransactionStatus
from app.core.time import utcnow
from app.models.base import Base, TimestampMixin
from app.models.types import UTCDateTime, enum_type

if TYPE_CHECKING:
    from app.models.compliance_log import ComplianceLog
    from app.models.user import User


class Transaction(TimestampMixin, Base):
    """An immutable payment instruction plus its mutable review state."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        # Idempotency is scoped to the sender. PostgreSQL and SQLite both allow
        # multiple NULLs, so transactions without a key remain unaffected.
        UniqueConstraint(
            "sender_id",
            "idempotency_key",
            name="uq_transactions_sender_idempotency_key",
        ),
        Index("ix_transactions_sender_created_at", "sender_id", "created_at"),
        Index("ix_transactions_receiver_created_at", "receiver_id", "created_at"),
        Index("ix_transactions_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    receiver_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Server-generated event time. Clients cannot backdate a transaction to
    # evade the velocity rule.
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    status: Mapped[TransactionStatus] = mapped_column(
        enum_type(TransactionStatus, "transaction_status"),
        nullable=False,
        default=TransactionStatus.PENDING_REVIEW,
    )

    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    sender: Mapped[User] = relationship(
        back_populates="sent_transactions",
        foreign_keys=[sender_id],
        lazy="selectin",
    )
    receiver: Mapped[User] = relationship(
        back_populates="received_transactions",
        foreign_keys=[receiver_id],
        lazy="selectin",
    )
    compliance_logs: Mapped[list[ComplianceLog]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="ComplianceLog.created_at",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Transaction id={self.id} amount={self.amount} {self.currency} "
            f"status={self.status.value}>"
        )
