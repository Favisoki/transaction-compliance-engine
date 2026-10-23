"""Tests for rule composition, ordering, and fail-safe behaviour."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.core.enums import Severity, TransactionStatus
from app.services.compliance import (
    ComplianceEngine,
    ComplianceRule,
    RuleContext,
    build_compliance_engine,
    register_rule,
)
from tests.test_rules import make_context


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        environment="test",
        high_risk_countries="KP,IR",
        velocity_max_transactions=3,
        large_transaction_threshold_usd=Decimal("10000"),
    )


def test_registry_builds_all_rules_in_order(settings: Settings) -> None:
    engine = build_compliance_engine(settings)
    assert engine.rule_codes == (
        "VELOCITY_CHECK",
        "HIGH_RISK_COUNTRY",
        "LARGE_TRANSACTION_KYC",
    )


def test_clean_transaction_is_approved(settings: Settings) -> None:
    decision = build_compliance_engine(settings).evaluate(
        make_context(sender_kyc=True, receiver_country="GB", amount="100.00")
    )

    assert decision.status is TransactionStatus.APPROVED
    assert decision.violations == ()
    assert decision.approved is True
    assert len(decision.rules_evaluated) == 3


def test_velocity_violation_flags_transaction(settings: Settings) -> None:
    decision = build_compliance_engine(settings).evaluate(make_context(recent_transaction_count=3))

    assert decision.status is TransactionStatus.FLAGGED
    assert [v.rule_code for v in decision.violations] == ["VELOCITY_CHECK"]


def test_large_transaction_flags_transaction(settings: Settings) -> None:
    decision = build_compliance_engine(settings).evaluate(
        make_context(amount="25000.00", sender_kyc=False)
    )

    assert decision.status is TransactionStatus.FLAGGED
    assert [v.rule_code for v in decision.violations] == ["LARGE_TRANSACTION_KYC"]


def test_reject_takes_precedence_and_all_rules_still_run(settings: Settings) -> None:
    decision = build_compliance_engine(settings).evaluate(
        make_context(
            receiver_country="KP",
            amount="25000.00",
            sender_kyc=False,
            recent_transaction_count=10,
        )
    )

    assert decision.status is TransactionStatus.REJECTED
    assert {v.rule_code for v in decision.violations} == {
        "VELOCITY_CHECK",
        "HIGH_RISK_COUNTRY",
        "LARGE_TRANSACTION_KYC",
    }


class ExplodingRule(ComplianceRule):
    code = "EXPLODING_RULE"
    name = "Exploding rule"
    severity = Severity.REJECT

    def evaluate(self, context: RuleContext):
        raise RuntimeError("boom")


def test_rule_exception_fails_closed(settings: Settings) -> None:
    engine = ComplianceEngine([ExplodingRule(settings)])
    decision = engine.evaluate(make_context(sender_kyc=True))

    assert decision.status is TransactionStatus.FLAGGED
    assert len(decision.violations) == 1
    violation = decision.violations[0]
    assert violation.rule_code == "RULE_EXECUTION_ERROR"
    assert violation.severity is Severity.FLAG
    assert violation.details["failed_rule_code"] == "EXPLODING_RULE"
    assert violation.details["error_type"] == "RuntimeError"


def test_duplicate_rule_codes_are_rejected() -> None:
    class DuplicateVelocityRule(ComplianceRule):
        code = "VELOCITY_CHECK"
        name = "Duplicate"
        severity = Severity.FLAG

        def evaluate(self, context: RuleContext):
            return None

    with pytest.raises(ValueError, match="Duplicate compliance rule code"):
        register_rule(DuplicateVelocityRule)


def test_engine_orders_rules_by_priority(settings: Settings) -> None:
    low = HighPriorityStub(settings, code="LOW", order=90)
    high = HighPriorityStub(settings, code="HIGH", order=1)
    engine = ComplianceEngine([low, high])

    assert engine.rule_codes == ("HIGH", "LOW")


class HighPriorityStub(ComplianceRule):
    name = "Stub"
    severity = Severity.INFO

    def __init__(self, settings: Settings, *, code: str, order: int) -> None:
        super().__init__(settings)
        self.code = code
        self.order = order

    def evaluate(self, context: RuleContext):
        return None
