"""Integration tests for Celery tasks and the manual review workflow.

Celery is not run as a separate process: tasks are executed synchronously via
``Task.apply`` after pointing the worker's session factory at the test database.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import utcnow
from app.models.transaction import Transaction
from app.workers import tasks


@pytest.fixture()
def worker(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
):
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    return tasks


def run_task(task, *args):
    return task.apply(args=list(args), throw=True).get()


def test_high_risk_destination_is_rejected_and_audited(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
) -> None:
    sender = make_user(kyc_verified=True)
    receiver = make_user(country_code="KP")
    transaction_id = submit_transaction(sender["id"], receiver["id"], amount="100.00")[
        "transaction_id"
    ]

    result = run_task(worker.evaluate_transaction_task, transaction_id)

    assert result["status"] == "REJECTED"
    assert result["violations"] == ["HIGH_RISK_COUNTRY"]
    assert result["skipped"] is False

    detail = client.get(f"/transactions/{transaction_id}").json()
    assert detail["status"] == "REJECTED"
    assert len(detail["compliance_logs"]) == 1
    log = detail["compliance_logs"][0]
    assert log["rule_code"] == "HIGH_RISK_COUNTRY"
    assert log["severity"] == "REJECT"
    assert log["details"]["country_code"] == "KP"

    page = client.get("/admin/flagged-transactions").json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == transaction_id


def test_large_unverified_transaction_goes_to_manual_review(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
) -> None:
    sender = make_user(kyc_verified=False)
    receiver = make_user(country_code="GB")
    transaction_id = submit_transaction(sender["id"], receiver["id"], amount="15000.00")[
        "transaction_id"
    ]

    result = run_task(worker.evaluate_transaction_task, transaction_id)

    assert result["status"] == "FLAGGED"
    assert result["violations"] == ["LARGE_TRANSACTION_KYC"]

    review = client.post(
        f"/admin/transactions/{transaction_id}/review",
        json={
            "decision": "APPROVED",
            "reviewer": "Compliance Officer",
            "notes": "Source of funds verified verbally.",
        },
    )

    assert review.status_code == 200, review.text
    reviewed = review.json()
    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_by"] == "Compliance Officer"
    assert reviewed["reviewed_at"] is not None
    assert reviewed["review_notes"] == "Source of funds verified verbally."
    assert any(log["rule_code"] == "MANUAL_REVIEW" for log in reviewed["compliance_logs"])

    # Approved transactions no longer appear in the review queue.
    page = client.get("/admin/flagged-transactions").json()
    assert page["total"] == 0

    # Terminal transactions cannot be reviewed twice.
    second_review = client.post(
        f"/admin/transactions/{transaction_id}/review",
        json={"decision": "REJECTED", "reviewer": "Compliance Officer"},
    )
    assert second_review.status_code == 409


def test_velocity_rule_flags_fourth_transaction(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
) -> None:
    sender = make_user(kyc_verified=True)
    receiver = make_user()
    transaction_ids = [
        submit_transaction(sender["id"], receiver["id"], amount="10.00")["transaction_id"]
        for _ in range(4)
    ]

    result = run_task(worker.evaluate_transaction_task, transaction_ids[-1])

    assert result["status"] == "FLAGGED"
    assert result["violations"] == ["VELOCITY_CHECK"]

    detail = client.get(f"/transactions/{transaction_ids[-1]}").json()
    assert detail["compliance_logs"][0]["details"]["observed_transactions"] == 4


def test_clean_transaction_is_approved(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
) -> None:
    sender = make_user(kyc_verified=True)
    receiver = make_user(country_code="GB")
    transaction_id = submit_transaction(sender["id"], receiver["id"], amount="50.00")[
        "transaction_id"
    ]

    result = run_task(worker.evaluate_transaction_task, transaction_id)

    assert result["status"] == "APPROVED"
    assert result["violations"] == []
    detail = client.get(f"/transactions/{transaction_id}").json()
    assert detail["status"] == "APPROVED"
    assert detail["compliance_logs"] == []


def test_evaluation_is_idempotent(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
) -> None:
    sender = make_user(kyc_verified=False)
    receiver = make_user()
    transaction_id = submit_transaction(sender["id"], receiver["id"], amount="20000.00")[
        "transaction_id"
    ]

    run_task(worker.evaluate_transaction_task, transaction_id)
    second = run_task(worker.evaluate_transaction_task, transaction_id)

    assert second["status"] == "FLAGGED"
    assert second["skipped"] is True
    detail = client.get(f"/transactions/{transaction_id}").json()
    assert len(detail["compliance_logs"]) == 1


def test_unknown_and_malformed_ids_are_handled(worker) -> None:
    missing = run_task(worker.evaluate_transaction_task, str(uuid.uuid4()))
    invalid = run_task(worker.evaluate_transaction_task, "not-a-uuid")

    assert missing["status"] == "NOT_FOUND"
    assert invalid["status"] == "INVALID_ID"


def test_reevaluate_endpoint_requeues_pending_transaction(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
    enqueued: list[uuid.UUID],
) -> None:
    sender = make_user(kyc_verified=True)
    receiver = make_user()
    transaction_id = submit_transaction(sender["id"], receiver["id"])["transaction_id"]
    assert len(enqueued) == 1

    response = client.post(f"/admin/transactions/{transaction_id}/reevaluate")

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING_REVIEW"
    assert len(enqueued) == 2

    run_task(worker.evaluate_transaction_task, transaction_id)
    conflict = client.post(f"/admin/transactions/{transaction_id}/reevaluate")
    assert conflict.status_code == 409


def test_admin_status_filter(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
) -> None:
    sender = make_user(kyc_verified=True)
    flagged_receiver = make_user()

    # A velocity flag produces FLAGGED.
    for _ in range(4):
        transaction_id = submit_transaction(sender["id"], flagged_receiver["id"], amount="10.00")[
            "transaction_id"
        ]
    run_task(worker.evaluate_transaction_task, transaction_id)

    # A sanctioned receiver produces REJECTED.
    rejected_receiver = make_user(country_code="IR")
    rejected_id = submit_transaction(sender["id"], rejected_receiver["id"], amount="10.00")[
        "transaction_id"
    ]
    run_task(worker.evaluate_transaction_task, rejected_id)

    flagged = client.get("/admin/flagged-transactions?status=FLAGGED").json()
    rejected = client.get("/admin/flagged-transactions?status=REJECTED").json()
    both = client.get("/admin/flagged-transactions").json()

    assert flagged["total"] == 1
    assert flagged["items"][0]["status"] == "FLAGGED"
    assert rejected["total"] == 1
    assert rejected["items"][0]["status"] == "REJECTED"
    assert both["total"] == 2

    invalid = client.get("/admin/flagged-transactions?status=APPROVED")
    assert invalid.status_code == 422


def test_stale_dispatch_republishes_old_pending_transactions(
    client: TestClient,
    make_user,
    submit_transaction,
    worker,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = make_user(kyc_verified=True)
    receiver = make_user()
    old_id = submit_transaction(sender["id"], receiver["id"])["transaction_id"]
    fresh_id = submit_transaction(sender["id"], receiver["id"])["transaction_id"]

    with session_factory() as db:
        old = db.get(Transaction, uuid.UUID(old_id))
        assert old is not None
        old.created_at = utcnow() - timedelta(minutes=10)
        db.commit()

    republished: list[uuid.UUID] = []
    monkeypatch.setattr(
        worker, "enqueue_transaction_evaluation", lambda tx_id: republished.append(tx_id)
    )

    result = run_task(worker.dispatch_stale_transactions_task)

    assert result["candidates"] == 1
    assert result["dispatched"] == 1
    assert [str(value) for value in republished] == [old_id]
    assert fresh_id not in {str(value) for value in republished}
