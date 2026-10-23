"""Value objects exchanged between the rule engine and its callers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.enums import Severity, TransactionStatus

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Everything a rule may inspect without touching the database.

    Pre-loading the sender, receiver, and velocity count in the service keeps
    individual rules pure and trivially unit-testable.
    """

    transaction: Transaction
    sender: User
    receiver: User
    recent_transaction_count: int
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class RuleViolation:
    rule_code: str
    rule_name: str
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ComplianceDecision:
    status: TransactionStatus
    violations: tuple[RuleViolation, ...]
    rules_evaluated: tuple[str, ...]
    evaluated_at: datetime

    @property
    def approved(self) -> bool:
        return self.status is TransactionStatus.APPROVED
