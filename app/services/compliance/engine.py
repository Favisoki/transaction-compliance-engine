"""The compliance decision engine."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.core.config import Settings
from app.core.enums import SEVERITY_RANK, Severity, TransactionStatus
from app.services.compliance.base import ComplianceRule, registered_rules
from app.services.compliance.types import (
    ComplianceDecision,
    RuleContext,
    RuleViolation,
)

logger = logging.getLogger(__name__)


class ComplianceEngine:
    """Run every rule and combine findings into a single decision.

    Rules are intentionally not short-circuited: collecting all violations gives
    a compliance officer the full audit trail for one transaction.
    """

    def __init__(self, rules: Sequence[ComplianceRule]) -> None:
        self._rules = tuple(sorted(rules, key=lambda rule: (rule.order, rule.code)))

    @property
    def rule_codes(self) -> tuple[str, ...]:
        return tuple(rule.code for rule in self._rules)

    def evaluate(self, context: RuleContext) -> ComplianceDecision:
        violations: list[RuleViolation] = []
        evaluated: list[str] = []

        for rule in self._rules:
            evaluated.append(rule.code)
            try:
                violation = rule.evaluate(context)
            except Exception as exc:
                # A rule bug must not let a transaction through silently. Flag
                # it for manual review and capture the failure in the audit log.
                logger.exception("Compliance rule %s failed", rule.code)
                violation = RuleViolation(
                    rule_code="RULE_EXECUTION_ERROR",
                    rule_name=rule.name,
                    severity=Severity.FLAG,
                    message=f"Rule {rule.code} could not be evaluated and requires manual review",
                    details={
                        "failed_rule_code": rule.code,
                        "error_type": type(exc).__name__,
                    },
                )
            if violation is not None:
                violations.append(violation)

        status = self._status_for(violations)
        return ComplianceDecision(
            status=status,
            violations=tuple(violations),
            rules_evaluated=tuple(evaluated),
            evaluated_at=context.evaluated_at,
        )

    @staticmethod
    def _status_for(violations: Sequence[RuleViolation]) -> TransactionStatus:
        decisive = [v for v in violations if v.severity is not Severity.INFO]
        if not decisive:
            return TransactionStatus.APPROVED
        highest = max(decisive, key=lambda violation: SEVERITY_RANK[violation.severity])
        if highest.severity is Severity.REJECT:
            return TransactionStatus.REJECTED
        return TransactionStatus.FLAGGED


def build_compliance_engine(
    settings: Settings,
    rules: Sequence[ComplianceRule] | None = None,
) -> ComplianceEngine:
    """Instantiate the registry-backed engine.

    ``rules`` exists for tests and for callers that want a custom rule set; the
    default path uses every registered rule.
    """

    instantiated = (
        list(rules)
        if rules is not None
        else [rule_cls(settings) for rule_cls in registered_rules()]
    )
    return ComplianceEngine(instantiated)
