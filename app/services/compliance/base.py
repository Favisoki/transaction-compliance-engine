"""Rule abstraction and registry.

New checks are added by subclassing :class:`ComplianceRule` and decorating the
class with :func:`register_rule`. No central ``if/elif`` block needs editing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.core.config import Settings
from app.core.enums import Severity
from app.services.compliance.types import RuleContext, RuleViolation


class ComplianceRule(ABC):
    """A single, independently testable compliance check."""

    code: ClassVar[str]
    name: ClassVar[str]
    severity: ClassVar[Severity]
    # Lower values run first. All rules run regardless of earlier findings so
    # the audit log captures the complete picture.
    order: ClassVar[int] = 100

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleViolation | None:
        """Return a violation when the check fails, otherwise ``None``."""

    def violation(
        self,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> RuleViolation:
        return RuleViolation(
            rule_code=self.code,
            rule_name=self.name,
            severity=self.severity,
            message=message,
            details=details or {},
        )


_RULE_REGISTRY: dict[str, type[ComplianceRule]] = {}


def register_rule[RuleT: ComplianceRule](rule_cls: type[RuleT]) -> type[RuleT]:
    """Register a rule class, rejecting duplicate codes at import time."""

    code = getattr(rule_cls, "code", None)
    if not code:
        raise ValueError(f"{rule_cls.__name__} must define a non-empty 'code'")
    if code in _RULE_REGISTRY:
        raise ValueError(f"Duplicate compliance rule code: {code!r}")
    _RULE_REGISTRY[code] = rule_cls
    return rule_cls


def registered_rules() -> tuple[type[ComplianceRule], ...]:
    """Return registered rule classes in deterministic execution order."""

    return tuple(sorted(_RULE_REGISTRY.values(), key=lambda cls: (cls.order, cls.code)))


def clear_registry_for_tests() -> None:
    """Test-only helper; production code must not mutate the registry at runtime."""

    _RULE_REGISTRY.clear()
