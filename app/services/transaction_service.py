"""Transaction persistence and compliance-officer workflows."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import Severity, TransactionStatus
from app.core.time import utcnow
from app.models.compliance_log import ComplianceLog
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.compliance import TransactionReviewRequest
from app.schemas.transaction import TransactionCreate
from app.services.exceptions import (
    InvalidStatusTransition,
    TransactionNotFound,
    UserNotFound,
)

logger = logging.getLogger(__name__)


class TransactionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        payload: TransactionCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[Transaction, bool]:
        """Persist a transaction, returning ``(transaction, replayed)``.

        The ``(sender_id, idempotency_key)`` unique constraint closes the race
        between two identical requests that both miss the initial lookup.
        """

        if idempotency_key is not None:
            existing = self._find_by_idempotency_key(payload.sender_id, idempotency_key)
            if existing is not None:
                return existing, True

        if self.db.get(User, payload.sender_id) is None:
            raise UserNotFound(payload.sender_id)
        if self.db.get(User, payload.receiver_id) is None:
            raise UserNotFound(payload.receiver_id)

        transaction = Transaction(
            sender_id=payload.sender_id,
            receiver_id=payload.receiver_id,
            amount=payload.amount,
            currency=payload.currency.value,
            description=payload.description,
            status=TransactionStatus.PENDING_REVIEW,
            idempotency_key=idempotency_key,
        )
        self.db.add(transaction)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if idempotency_key is not None:
                existing = self._find_by_idempotency_key(payload.sender_id, idempotency_key)
                if existing is not None:
                    return existing, True
            raise

        self.db.refresh(transaction)
        logger.info("Transaction %s persisted with status PENDING_REVIEW", transaction.id)
        return transaction, False

    def get(self, transaction_id: uuid.UUID) -> Transaction:
        transaction = self.db.get(Transaction, transaction_id)
        if transaction is None:
            raise TransactionNotFound(transaction_id)
        return transaction

    def review(
        self,
        transaction_id: uuid.UUID,
        review: TransactionReviewRequest,
    ) -> Transaction:
        transaction = self._get_for_update(transaction_id)
        if transaction.status is not TransactionStatus.FLAGGED:
            raise InvalidStatusTransition(transaction_id, transaction.status.value, "review")

        reviewer = review.reviewer
        notes = review.notes
        transaction.status = TransactionStatus(review.decision.value)
        transaction.reviewed_by = reviewer
        transaction.reviewed_at = utcnow()
        transaction.review_notes = notes

        transaction.compliance_logs.append(
            ComplianceLog(
                rule_code="MANUAL_REVIEW",
                rule_name="Manual compliance review",
                severity=Severity.INFO,
                message=f"Transaction manually {review.decision.value.lower()} by {reviewer}",
                details={
                    "reviewer": reviewer,
                    "decision": review.decision.value,
                    "notes": notes,
                },
            )
        )

        self.db.commit()
        self.db.refresh(transaction)
        logger.info(
            "Transaction %s manually %s by %s",
            transaction_id,
            review.decision.value,
            reviewer,
        )
        return transaction

    def list_flagged(
        self,
        *,
        statuses: Sequence[TransactionStatus],
        limit: int,
        offset: int,
    ) -> tuple[list[Transaction], int]:
        filters = (Transaction.status.in_(statuses),)

        total = self.db.scalar(select(func.count(Transaction.id)).where(*filters)) or 0
        items = list(
            self.db.scalars(
                select(Transaction)
                .where(*filters)
                .order_by(Transaction.created_at.desc(), Transaction.id)
                .limit(limit)
                .offset(offset)
            ).all()
        )
        return items, total

    def get_for_requeue(self, transaction_id: uuid.UUID) -> Transaction:
        transaction = self._get_for_update(transaction_id)
        if transaction.status is not TransactionStatus.PENDING_REVIEW:
            raise InvalidStatusTransition(transaction_id, transaction.status.value, "re-evaluate")
        return transaction

    def _get_for_update(self, transaction_id: uuid.UUID) -> Transaction:
        transaction = self.db.execute(
            select(Transaction).where(Transaction.id == transaction_id).with_for_update()
        ).scalar_one_or_none()
        if transaction is None:
            raise TransactionNotFound(transaction_id)
        return transaction

    def _find_by_idempotency_key(self, sender_id: uuid.UUID, key: str) -> Transaction | None:
        return self.db.execute(
            select(Transaction).where(
                Transaction.sender_id == sender_id,
                Transaction.idempotency_key == key,
            )
        ).scalar_one_or_none()
