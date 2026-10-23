"""Evaluate a persisted transaction and record the audit trail."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.enums import TransactionStatus
from app.core.time import utcnow
from app.models.compliance_log import ComplianceLog
from app.models.transaction import Transaction
from app.models.user import User
from app.services.compliance import (
    ComplianceEngine,
    RuleContext,
    RuleViolation,
    build_compliance_engine,
)
from app.services.exceptions import InconsistentTransactionError, TransactionNotFound

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    transaction_id: uuid.UUID
    status: TransactionStatus
    violations: tuple[RuleViolation, ...]
    skipped: bool = False


class ComplianceService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        engine: ComplianceEngine | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.engine = engine or build_compliance_engine(self.settings)

    def evaluate_transaction(self, transaction_id: uuid.UUID) -> EvaluationOutcome:
        """Evaluate once and persist the decision.

        Idempotent by design: Celery provides at-least-once delivery, so a
        duplicate task for an already-decided transaction is a no-op.
        """

        transaction = self.db.execute(
            select(Transaction).where(Transaction.id == transaction_id).with_for_update()
        ).scalar_one_or_none()
        if transaction is None:
            raise TransactionNotFound(transaction_id)

        if transaction.status is not TransactionStatus.PENDING_REVIEW:
            logger.info(
                "Skipping transaction %s: already in terminal status %s",
                transaction_id,
                transaction.status.value,
            )
            return EvaluationOutcome(
                transaction_id=transaction_id,
                status=transaction.status,
                violations=(),
                skipped=True,
            )

        sender = self.db.get(User, transaction.sender_id)
        receiver = self.db.get(User, transaction.receiver_id)
        if sender is None or receiver is None:
            raise InconsistentTransactionError(
                transaction_id, "sender or receiver user record is missing"
            )

        now = utcnow()
        recent_count = self._recent_transaction_count(
            sender_id=transaction.sender_id,
            transaction_id=transaction.id,
            now=now,
        )

        context = RuleContext(
            transaction=transaction,
            sender=sender,
            receiver=receiver,
            recent_transaction_count=recent_count,
            evaluated_at=now,
        )
        decision = self.engine.evaluate(context)

        for violation in decision.violations:
            transaction.compliance_logs.append(
                ComplianceLog(
                    rule_code=violation.rule_code,
                    rule_name=violation.rule_name,
                    severity=violation.severity,
                    message=violation.message,
                    details=violation.details,
                )
            )

        transaction.status = decision.status
        self.db.commit()

        logger.info(
            "Transaction %s evaluated as %s (%d violation(s), rules=%s)",
            transaction_id,
            decision.status.value,
            len(decision.violations),
            ",".join(decision.rules_evaluated),
        )
        return EvaluationOutcome(
            transaction_id=transaction_id,
            status=decision.status,
            violations=decision.violations,
        )

    def _recent_transaction_count(
        self,
        *,
        sender_id: uuid.UUID,
        transaction_id: uuid.UUID,
        now: datetime,
    ) -> int:
        window_start = now - timedelta(seconds=self.settings.velocity_window_seconds)
        count = self.db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.sender_id == sender_id,
                Transaction.id != transaction_id,
                Transaction.created_at >= window_start,
            )
        )
        return int(count or 0)
