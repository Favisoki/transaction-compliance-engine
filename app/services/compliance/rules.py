"""Built-in compliance rules.

Each rule is a pure function of the :class:`RuleContext` plus settings. Adding
a rule therefore requires a new class and a registration decorator only.
"""

from __future__ import annotations

from app.core.enums import Severity
from app.services.compliance.base import ComplianceRule, register_rule
from app.services.compliance.types import RuleContext, RuleViolation
from app.services.fx import convert_to_usd


@register_rule
class VelocityRule(ComplianceRule):
    """Flag senders who submit more than the allowed number of transactions
    within a rolling window.

    The current transaction counts as one, so the limit is inclusive: with the
    default of 3 per 300 seconds, the fourth transaction is flagged.
    """

    code = "VELOCITY_CHECK"
    name = "Transaction velocity"
    severity = Severity.FLAG
    order = 10

    def evaluate(self, context: RuleContext) -> RuleViolation | None:
        observed = context.recent_transaction_count + 1
        if observed <= self.settings.velocity_max_transactions:
            return None

        return self.violation(
            (
                f"Sender submitted {observed} transactions within "
                f"{self.settings.velocity_window_seconds} seconds "
                f"(limit: {self.settings.velocity_max_transactions})"
            ),
            details={
                "sender_id": str(context.sender.id),
                "observed_transactions": observed,
                "max_transactions": self.settings.velocity_max_transactions,
                "window_seconds": self.settings.velocity_window_seconds,
            },
        )


@register_rule
class HighRiskCountryRule(ComplianceRule):
    """Reject transfers whose destination is a sanctioned or high-risk country."""

    code = "HIGH_RISK_COUNTRY"
    name = "High-risk destination country"
    severity = Severity.REJECT
    order = 20

    def evaluate(self, context: RuleContext) -> RuleViolation | None:
        country = context.receiver.country_code.upper()
        high_risk = self.settings.high_risk_country_codes
        if country not in high_risk:
            return None

        return self.violation(
            f"Receiver is resident in high-risk jurisdiction {country}",
            details={
                "receiver_id": str(context.receiver.id),
                "country_code": country,
                "high_risk_countries": sorted(high_risk),
            },
        )


@register_rule
class LargeTransactionKycRule(ComplianceRule):
    """Flag large transfers from customers who have not completed KYC.

    Amounts are normalised to USD before comparison so the threshold cannot be
    bypassed by denominating the transfer in another currency.
    """

    code = "LARGE_TRANSACTION_KYC"
    name = "Large transaction without KYC"
    severity = Severity.FLAG
    order = 30

    def evaluate(self, context: RuleContext) -> RuleViolation | None:
        if context.sender.kyc_verified:
            return None

        amount_usd = convert_to_usd(
            context.transaction.amount,
            context.transaction.currency,
            self.settings,
        )
        threshold = self.settings.large_transaction_threshold_usd
        if amount_usd <= threshold:
            return None

        return self.violation(
            (
                f"Transaction of {context.transaction.amount} "
                f"{context.transaction.currency} (~{amount_usd} USD) exceeds the "
                f"{threshold} USD threshold and the sender is not KYC verified"
            ),
            details={
                "sender_id": str(context.sender.id),
                "amount": str(context.transaction.amount),
                "currency": context.transaction.currency,
                "amount_usd": str(amount_usd),
                "threshold_usd": str(threshold),
                "kyc_verified": False,
            },
        )
