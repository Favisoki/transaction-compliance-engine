"""Celery tasks: compliance evaluation and delivery recovery."""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.celery_app import (
    DISPATCH_STALE_TRANSACTIONS_TASK,
    EVALUATE_TRANSACTION_TASK,
    celery_app,
)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.enums import TransactionStatus
from app.core.time import utcnow
from app.models.transaction import Transaction
from app.services.compliance_service import ComplianceService
from app.services.dispatch import enqueue_transaction_evaluation
from app.services.exceptions import InconsistentTransactionError, TransactionNotFound

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name=EVALUATE_TRANSACTION_TASK,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
)
def evaluate_transaction_task(self, transaction_id: str) -> dict[str, object]:
    """Evaluate one transaction against the compliance rule engine."""

    try:
        tx_id = UUID(transaction_id)
    except (TypeError, ValueError):
        logger.error("Discarding compliance task with invalid id %r", transaction_id)
        return {"transaction_id": transaction_id, "status": "INVALID_ID"}

    try:
        with SessionLocal() as db:
            outcome = ComplianceService(db).evaluate_transaction(tx_id)
    except TransactionNotFound:
        logger.error("Transaction %s no longer exists; dropping evaluation", tx_id)
        return {"transaction_id": str(tx_id), "status": "NOT_FOUND"}
    except InconsistentTransactionError:
        # Retrying cannot repair corrupt references, so surface it and stop.
        logger.exception("Cannot evaluate inconsistent transaction %s", tx_id)
        return {"transaction_id": str(tx_id), "status": "INCONSISTENT"}
    except OperationalError:
        logger.warning("Database unavailable while evaluating %s; will retry", tx_id)
        raise

    return {
        "transaction_id": str(outcome.transaction_id),
        "status": outcome.status.value,
        "skipped": outcome.skipped,
        "violations": [violation.rule_code for violation in outcome.violations],
    }


@celery_app.task(name=DISPATCH_STALE_TRANSACTIONS_TASK)
def dispatch_stale_transactions_task() -> dict[str, int]:
    """Re-publish evaluations for transactions stuck in ``PENDING_REVIEW``.

    This closes the gap when the API committed a transaction but failed to
    reach the broker. Duplicate delivery is harmless because the evaluation
    task is idempotent.
    """

    settings = get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.stale_pending_seconds)

    with SessionLocal() as db:
        transaction_ids = list(
            db.scalars(
                select(Transaction.id)
                .where(
                    Transaction.status == TransactionStatus.PENDING_REVIEW,
                    Transaction.created_at <= cutoff,
                )
                .order_by(Transaction.created_at)
                .limit(settings.stale_dispatch_batch_size)
            ).all()
        )

    dispatched = 0
    for transaction_id in transaction_ids:
        try:
            enqueue_transaction_evaluation(transaction_id)
        except Exception:
            logger.exception("Stale-dispatch failed; broker may be unavailable")
            break
        dispatched += 1

    logger.info(
        "Stale dispatch: %d candidate(s), %d re-published", len(transaction_ids), dispatched
    )
    return {"candidates": len(transaction_ids), "dispatched": dispatched}
