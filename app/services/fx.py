"""Mock FX conversion used by the large-transaction rule."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.core.config import Settings

_CENT = Decimal("0.01")


def convert_to_usd(amount: Decimal, currency: str, settings: Settings) -> Decimal:
    """Convert an amount to USD using the configured mock rate table.

    Raises:
        ValueError: if the currency has no configured rate. The API schema
            restricts currencies to the supported set, so this indicates a
            configuration problem rather than bad user input.
    """

    rate = settings.fx_rates_usd.get(currency.upper())
    if rate is None:
        raise ValueError(f"No FX rate configured for currency {currency!r}")
    return (amount * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
