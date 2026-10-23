"""Unit tests for individual compliance rules."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.core.enums import Currency, Severity, TransactionStatus
from app.core.time import utcnow
from app.models.transaction import Transaction
from app.models.user import User
from app.services.compliance.rules import (
    HighRiskCountryRule,
    LargeTransactionKycRule,
    VelocityRule,
)
from app.services.compliance.types import RuleContext


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        environment="test",
        high_risk_countries="KP,IR,SY",
        velocity_max_transactions=3,
        velocity_window_seconds=300,
        large_transaction_threshold_usd=Decimal("10000"),
    )


def make_user(
    *,
    country_code: str = "US",
    kyc_verified: bool = False,
) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        full_name="Test User",
        country_code=country_code,
        risk_score=20,
        kyc_verified=kyc_verified,
    )


def make_context(
    *,
    sender_kyc: bool = False,
    sender_country: str = "US",
    receiver_country: str = "US",
    amount: str = "100.00",
    currency: str = "USD",
    recent_transaction_count: int = 0,
) -> RuleContext:
    sender = make_user(country_code=sender_country, kyc_verified=sender_kyc)
    receiver = make_user(country_code=receiver_country)
    transaction = Transaction(
        id=uuid.uuid4(),
        sender_id=sender.id,
        receiver_id=receiver.id,
        amount=Decimal(amount),
        currency=currency,
        status=TransactionStatus.PENDING_REVIEW,
        created_at=utcnow(),
    )
    return RuleContext(
        transaction=transaction,
        sender=sender,
        receiver=receiver,
        recent_transaction_count=recent_transaction_count,
        evaluated_at=utcnow(),
    )


class TestVelocityRule:
    def test_allows_activity_at_the_limit(self, settings: Settings) -> None:
        # Three transactions in the window including the current one.
        context = make_context(recent_transaction_count=2)
        assert VelocityRule(settings).evaluate(context) is None

    def test_flags_the_fourth_transaction(self, settings: Settings) -> None:
        context = make_context(recent_transaction_count=3)
        violation = VelocityRule(settings).evaluate(context)

        assert violation is not None
        assert violation.rule_code == "VELOCITY_CHECK"
        assert violation.severity is Severity.FLAG
        assert violation.details["observed_transactions"] == 4
        assert violation.details["max_transactions"] == 3
        assert violation.details["window_seconds"] == 300

    def test_uses_configured_limit(self) -> None:
        settings = Settings(
            environment="test",
            velocity_max_transactions=10,
            velocity_window_seconds=60,
        )
        assert VelocityRule(settings).evaluate(make_context(recent_transaction_count=8)) is None
        violation = VelocityRule(settings).evaluate(make_context(recent_transaction_count=10))
        assert violation is not None
        assert "11" in violation.message


class TestHighRiskCountryRule:
    @pytest.mark.parametrize("country", ["KP", "IR", "SY"])
    def test_rejects_high_risk_destinations(self, settings: Settings, country: str) -> None:
        context = make_context(receiver_country=country)
        violation = HighRiskCountryRule(settings).evaluate(context)

        assert violation is not None
        assert violation.rule_code == "HIGH_RISK_COUNTRY"
        assert violation.severity is Severity.REJECT
        assert violation.details["country_code"] == country

    def test_allows_low_risk_destination(self, settings: Settings) -> None:
        assert HighRiskCountryRule(settings).evaluate(make_context(receiver_country="GB")) is None

    def test_country_matching_is_case_insensitive(self, settings: Settings) -> None:
        context = make_context(receiver_country="kp")
        assert HighRiskCountryRule(settings).evaluate(context) is not None


class TestLargeTransactionKycRule:
    def test_allows_amount_at_threshold(self, settings: Settings) -> None:
        context = make_context(amount="10000.00", sender_kyc=False)
        assert LargeTransactionKycRule(settings).evaluate(context) is None

    def test_flags_amount_above_threshold_without_kyc(self, settings: Settings) -> None:
        context = make_context(amount="10000.01", sender_kyc=False)
        violation = LargeTransactionKycRule(settings).evaluate(context)

        assert violation is not None
        assert violation.rule_code == "LARGE_TRANSACTION_KYC"
        assert violation.severity is Severity.FLAG
        assert violation.details["amount_usd"] == "10000.01"

    def test_allows_large_amount_for_verified_user(self, settings: Settings) -> None:
        context = make_context(amount="500000.00", sender_kyc=True)
        assert LargeTransactionKycRule(settings).evaluate(context) is None

    def test_converts_foreign_currency_before_comparing(self, settings: Settings) -> None:
        # 10,000 EUR is roughly 10,800 USD at the mock rate.
        context = make_context(amount="10000.00", currency="EUR", sender_kyc=False)
        violation = LargeTransactionKycRule(settings).evaluate(context)

        assert violation is not None
        assert violation.details["amount_usd"] == "10800.00"
        assert violation.details["currency"] == "EUR"

    def test_small_foreign_currency_amount_is_allowed(self, settings: Settings) -> None:
        context = make_context(amount="100.00", currency="NGN", sender_kyc=False)
        assert LargeTransactionKycRule(settings).evaluate(context) is None

    def test_every_supported_currency_has_a_rate(self, settings: Settings) -> None:
        missing = {currency.value for currency in Currency} - set(settings.fx_rates_usd)
        assert missing == set()
