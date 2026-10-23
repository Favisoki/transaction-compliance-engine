"""Compliance-officer endpoints for reviewing and re-evaluating transactions."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.enums import TransactionStatus
from app.schemas.compliance import TransactionReviewRequest
from app.schemas.transaction import (
    FlaggedTransactionPage,
    TransactionAccepted,
    TransactionDetail,
)
from app.services.dispatch import enqueue_transaction_evaluation
from app.services.exceptions import InvalidStatusTransition, TransactionNotFound
from app.services.transaction_service import TransactionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

FlagFilter = Literal["FLAGGED", "REJECTED"]


@router.get(
    "/flagged-transactions",
    response_model=FlaggedTransactionPage,
    summary="List transactions awaiting or requiring compliance review",
)
def list_flagged_transactions(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[
        FlagFilter | None,
        Query(alias="status", description="Optionally restrict to FLAGGED or REJECTED"),
    ] = None,
) -> FlaggedTransactionPage:
    statuses = (
        [TransactionStatus(status_filter)]
        if status_filter is not None
        else [TransactionStatus.FLAGGED, TransactionStatus.REJECTED]
    )
    items, total = TransactionService(db).list_flagged(
        statuses=statuses,
        limit=limit,
        offset=offset,
    )
    return FlaggedTransactionPage(
        items=[TransactionDetail.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/transactions/{transaction_id}/review",
    response_model=TransactionDetail,
    summary="Approve or reject a flagged transaction",
    responses={
        404: {"description": "Transaction not found"},
        409: {"description": "Transaction is not in FLAGGED status"},
    },
)
def review_transaction(
    transaction_id: uuid.UUID,
    review: TransactionReviewRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TransactionDetail:
    try:
        transaction = TransactionService(db).review(transaction_id, review)
    except TransactionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TransactionDetail.model_validate(transaction)


@router.post(
    "/transactions/{transaction_id}/reevaluate",
    response_model=TransactionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-publish a pending transaction for evaluation",
    responses={
        404: {"description": "Transaction not found"},
        409: {"description": "Transaction is no longer pending"},
        503: {"description": "Message broker unavailable"},
    },
)
def reevaluate_transaction(
    transaction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> TransactionAccepted:
    try:
        transaction = TransactionService(db).get_for_requeue(transaction_id)
    except TransactionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    try:
        enqueue_transaction_evaluation(transaction.id)
    except Exception as exc:
        logger.exception("Failed to re-enqueue transaction %s", transaction.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not enqueue the transaction; retry shortly",
        ) from exc

    return TransactionAccepted(
        transaction_id=transaction.id,
        status=transaction.status,
        message="Transaction re-queued for compliance review",
    )
