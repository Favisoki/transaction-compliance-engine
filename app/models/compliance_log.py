from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Severity
from app.core.time import utcnow
from app.models.base import Base
from app.models.types import UTCDateTime, enum_type

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class ComplianceLog(Base):
    """Append-only audit record explaining a compliance decision.

    One row is written per rule violation, plus one row per manual review. The
    log intentionally duplicates the rule name and severity: audit records must
    remain readable even if a rule is renamed or removed later.
    """

    __tablename__ = "compliance_logs"
    __table_args__ = (
        Index("ix_compliance_logs_transaction_created_at", "transaction_id", "created_at"),
        Index("ix_compliance_logs_rule_code", "rule_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )

    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        enum_type(Severity, "compliance_log_severity"),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(String(1024), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    transaction: Mapped[Transaction] = relationship(back_populates="compliance_logs")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ComplianceLog rule={self.rule_code!r} severity={self.severity.value}>"
