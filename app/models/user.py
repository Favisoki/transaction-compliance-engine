from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Uuid, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class User(TimestampMixin, Base):
    """A customer whose transactions are screened.

    ``risk_score`` and ``kyc_verified`` are deliberately stored on the user:
    compliance decisions often depend on the customer's standing rather than
    only on a single transaction.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_users_risk_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    risk_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    kyc_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    sent_transactions: Mapped[list[Transaction]] = relationship(
        back_populates="sender",
        foreign_keys="Transaction.sender_id",
    )
    received_transactions: Mapped[list[Transaction]] = relationship(
        back_populates="receiver",
        foreign_keys="Transaction.receiver_id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} country={self.country_code!r} kyc={self.kyc_verified}>"
