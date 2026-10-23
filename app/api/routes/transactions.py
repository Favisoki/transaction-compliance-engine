"""Transaction ingestion and lookup endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.transaction import (
    TransactionAccepted,
    TransactionCreate,
    TransactionDetail,
)
from app.services.dispatch import enqueue_transaction_evaluation
from app.services.exceptions import TransactionNotFound, UserNotFound
from app.services.transaction_service import TransactionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post(
    "",
    response_model=TransactionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a transaction for compliance review",
    responses={
        202: {"description": "Persisted and queued for asynchronous evaluation"},
        422: {"description": "Invalid payload or unknown sender/receiver"},
    },
)
def create_transaction(
    payload: TransactionCreate,
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=64,
            description="Optional client-generated key, unique per sender.",
        ),
    ] = None,
) -> TransactionAccepted:
    key = idempotency_key.strip() if idempotency_key else None
    if key == "":
        key = None

    service = TransactionService(db)
    try:
        transaction, replayed = service.create(payload, idempotency_key=key)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    if not replayed:
        # Publish after the commit: a worker must never receive an id that is
        # not yet visible in the database.
        try:
            enqueue_transaction_evaluation(transaction.id)
        except Exception:
            logger.exception(
                "Failed to enqueue transaction %s; stale dispatcher will retry",
                transaction.id,
            )

    return TransactionAccepted(
        transaction_id=transaction.id,
        status=transaction.status,
        replayed=replayed,
        message=(
            "Existing transaction returned for idempotency key"
            if replayed
            else "Transaction accepted for compliance review"
        ),
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionDetail,
    summary="Fetch a transaction and its compliance audit trail",
    responses={404: {"description": "Transaction not found"}},
)
def get_transaction(
    transaction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> TransactionDetail:
    try:
        transaction = TransactionService(db).get(transaction_id)
    except TransactionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TransactionDetail.model_validate(transaction)
