"""Shared schema helpers and validators."""

from __future__ import annotations

import re

COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")


def normalize_country_code(value: str) -> str:
    """Normalise to an uppercase ISO-3166 alpha-2 code."""

    code = value.strip().upper()
    if not COUNTRY_CODE_PATTERN.fullmatch(code):
        raise ValueError("country_code must be a two-letter ISO-3166 code, e.g. 'US'")
    return code


def normalize_email(value: str) -> str:
    return value.strip().lower()
