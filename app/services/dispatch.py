"""Task publishing boundary.

The Celery import is deferred so that importing the API (and running API tests)
never requires a broker connection or a worker process.
"""

from __future__ import annotations

import uuid


def enqueue_transaction_evaluation(transaction_id: uuid.UUID) -> None:
    """Publish an evaluation event to the Celery queue.

    Delivery is best-effort at this call site. If publishing fails, the
    transaction remains ``PENDING_REVIEW`` and the periodic stale-dispatch task
    retries it later.
    """

    from app.workers.tasks import evaluate_transaction_task

    evaluate_transaction_task.delay(str(transaction_id))
