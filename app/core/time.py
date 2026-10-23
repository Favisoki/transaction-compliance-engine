"""Time helpers. All timestamps in the system are UTC and timezone-aware."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""

    return datetime.now(UTC)
