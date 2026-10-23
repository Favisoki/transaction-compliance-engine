"""Custom SQLAlchemy types shared by the models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Store timestamps as UTC and always return timezone-aware values.

    PostgreSQL ``timestamptz`` handles this natively; SQLite (used by the test
    suite) drops the offset. Normalising in one place keeps comparisons and API
    serialization consistent across both backends.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def enum_type(enum_cls: type[Enum], name: str) -> SAEnum:
    """Portable enum column: VARCHAR plus a CHECK constraint.

    Native database enums complicate migrations and rollbacks, so values are
    stored as strings while still being validated at the application layer.
    """

    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
        create_constraint=True,
    )
