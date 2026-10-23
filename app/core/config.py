"""Application configuration.

Settings are read from environment variables (and an optional ``.env`` file).
The ``Settings`` object is the single source of truth for infrastructure and
compliance-rule configuration; it is injected into services and rules so that
tests can use deterministic values.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Transaction Compliance Engine"
    app_version: str = "1.0.0"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    # Creating tables at startup keeps local development frictionless. A real
    # deployment should run versioned migrations and set this to false.
    auto_create_tables: bool = True

    database_url: str = "postgresql+psycopg2://compliance:compliance@localhost:5432/compliance"
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1)
    database_pool_max_overflow: int = Field(default=10, ge=0)

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_always_eager: bool = False
    celery_task_eager_propagates: bool = False
    celery_task_time_limit_seconds: int = Field(default=60, ge=1)
    # Prefork is the right default on Linux. Celery's prefork pool can fail on
    # macOS/Python 3.13 due to spawn-based multiprocessing, so the Celery app
    # selects "solo" there unless this is set explicitly.
    celery_worker_pool: Literal["solo", "prefork", "threads", "processes"] | None = None

    # A periodic task re-dispatches transactions that are still pending. This
    # provides at-least-once delivery if the API cannot reach the broker.
    stale_pending_seconds: int = Field(default=120, ge=30)
    stale_dispatch_batch_size: int = Field(default=100, ge=1, le=1000)
    stale_dispatch_interval_seconds: int = Field(default=60, ge=5)

    # Rule configuration
    velocity_window_seconds: int = Field(default=300, ge=1)
    velocity_max_transactions: int = Field(default=3, ge=1)

    # Comma-separated ISO-3166 alpha-2 codes
    high_risk_countries: str = "KP,IR,SY,CU,SD,MM,BY"

    large_transaction_threshold_usd: Decimal = Decimal("10000")

    # Mock FX table: value of one unit of the currency in USD. A real system
    # would replace this with a rate provider and persist the rate used.
    fx_rates_usd: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "USD": Decimal("1"),
            "EUR": Decimal("1.12"),
            "GBP": Decimal("1.34"),
            "CAD": Decimal("0.71"),
            "AUD": Decimal("0.70"),
            "CHF": Decimal("1.21"),
            "JPY": Decimal("0.0063"),
            "NGN": Decimal("0.00075"),
            "ZAR": Decimal("0.061"),
            "AED": Decimal("0.272"),
            "INR": Decimal("0.011"),
            "CNY": Decimal("0.15"),
        }
    )

    @field_validator("large_transaction_threshold_usd")
    @classmethod
    def _threshold_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("large_transaction_threshold_usd must be positive")
        return value

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def high_risk_country_codes(self) -> frozenset[str]:
        return frozenset(
            code.strip().upper() for code in self.high_risk_countries.split(",") if code.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
