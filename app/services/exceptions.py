"""Domain exceptions mapped to HTTP responses by the API layer."""

from __future__ import annotations

import uuid


class DomainError(Exception):
    """Base class for expected, user-facing domain failures."""


class UserNotFound(DomainError):
    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        super().__init__(f"User {user_id} does not exist")


class TransactionNotFound(DomainError):
    def __init__(self, transaction_id: uuid.UUID) -> None:
        self.transaction_id = transaction_id
        super().__init__(f"Transaction {transaction_id} does not exist")


class InvalidStatusTransition(DomainError):
    def __init__(self, transaction_id: uuid.UUID, current: str, action: str) -> None:
        self.transaction_id = transaction_id
        self.current = current
        self.action = action
        super().__init__(f"Cannot {action} transaction {transaction_id} while it is {current}")


class InconsistentTransactionError(DomainError):
    def __init__(self, transaction_id: uuid.UUID, reason: str) -> None:
        self.transaction_id = transaction_id
        super().__init__(f"Transaction {transaction_id} is inconsistent: {reason}")
