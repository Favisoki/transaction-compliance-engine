"""Celery application configuration."""

from __future__ import annotations

import sys

from celery import Celery

from app.core.config import get_settings

EVALUATE_TRANSACTION_TASK = "compliance.evaluate_transaction"
DISPATCH_STALE_TRANSACTIONS_TASK = "compliance.dispatch_stale_transactions"

_settings = get_settings()

# Celery's prefork pool can fail on macOS with Python 3.13 because the default
# multiprocessing start method is "spawn" and the worker's localized task table
# is not inherited. Docker/Linux keeps the throughput-oriented prefork pool.
_default_pool = "solo" if sys.platform == "darwin" else "prefork"
_worker_pool = _settings.celery_worker_pool or _default_pool

celery_app = Celery(
    "transaction_compliance",
    broker=_settings.broker_url,
    backend=_settings.result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_pool=_worker_pool,
    # At-least-once semantics: acknowledge only after the task completes.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=_settings.celery_task_time_limit_seconds,
    task_soft_time_limit=max(_settings.celery_task_time_limit_seconds - 5, 1),
    task_always_eager=_settings.celery_task_always_eager,
    task_eager_propagates=_settings.celery_task_eager_propagates,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    beat_schedule={
        "dispatch-stale-pending-transactions": {
            "task": DISPATCH_STALE_TRANSACTIONS_TASK,
            "schedule": float(_settings.stale_dispatch_interval_seconds),
        }
    },
)
