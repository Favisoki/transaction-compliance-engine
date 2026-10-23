"""Shared domain enums used by models, schemas, and the rule engine."""

from __future__ import annotations

from enum import StrEnum


class TransactionStatus(StrEnum):
    """Lifecycle of a transaction as it moves through the pipeline."""

    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class Severity(StrEnum):
    """Severity attached to a rule violation or an audit log entry."""

    INFO = "INFO"
    FLAG = "FLAG"
    REJECT = "REJECT"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.FLAG: 1,
    Severity.REJECT: 2,
}


class Currency(StrEnum):
    """Currencies accepted by the API and supported by the mock FX table."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CAD = "CAD"
    AUD = "AUD"
    CHF = "CHF"
    JPY = "JPY"
    NGN = "NGN"
    ZAR = "ZAR"
    AED = "AED"
    INR = "INR"
    CNY = "CNY"


class ReviewDecision(StrEnum):
    """Outcomes available to a compliance officer reviewing a flagged transaction."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
