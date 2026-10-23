"""API-level tests for ingestion, validation, and idempotency."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.routes import transactions as transaction_routes
from app.core.enums import TransactionStatus


def test_create_transaction_is_accepted_and_queued(
    client: TestClient,
    make_user,
    submit_transaction,
    enqueued: list[uuid.UUID],
) -> None:
    sender = make_user()
    receiver = make_user(country_code="GB")

    body = submit_transaction(sender["id"], receiver["id"], amount="1250.50")

    assert body["status"] == TransactionStatus.PENDING_REVIEW.value
    assert body["replayed"] is False
    assert len(enqueued) == 1
    assert str(enqueued[0]) == body["transaction_id"]

    detail = client.get(f"/transactions/{body['transaction_id']}")
    assert detail.status_code == 200
    transaction = detail.json()
    assert transaction["status"] == "PENDING_REVIEW"
    assert transaction["amount"] == "1250.50"
    assert transaction["currency"] == "USD"
    assert transaction["sender"]["id"] == sender["id"]
    assert transaction["receiver"]["id"] == receiver["id"]
    assert transaction["compliance_logs"] == []


def test_unknown_transaction_returns_404(client: TestClient) -> None:
    response = client.get(f"/transactions/{uuid.uuid4()}")
    assert response.status_code == 404


def test_self_transfer_is_rejected(
    client: TestClient,
    make_user,
    submit_transaction,
    enqueued: list[uuid.UUID],
) -> None:
    user = make_user()
    response = client.post(
        "/transactions",
        json={
            "sender_id": user["id"],
            "receiver_id": user["id"],
            "amount": "10.00",
            "currency": "USD",
        },
    )

    assert response.status_code == 422
    assert enqueued == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "0"),
        ("amount", "-5.00"),
        ("amount", "1.234"),
        ("currency", "XYZ"),
        ("description", "   "),
        ("unexpected_field", "nope"),
    ],
)
def test_invalid_payloads_are_rejected(
    client: TestClient,
    make_user,
    enqueued: list[uuid.UUID],
    field: str,
    value: str,
) -> None:
    sender = make_user()
    receiver = make_user()
    payload = {
        "sender_id": sender["id"],
        "receiver_id": receiver["id"],
        "amount": "10.00",
        "currency": "USD",
    }
    payload[field] = value

    response = client.post("/transactions", json=payload)

    assert response.status_code == 422, response.text
    assert enqueued == []


def test_unknown_sender_is_rejected(
    client: TestClient,
    make_user,
    enqueued: list[uuid.UUID],
) -> None:
    receiver = make_user()
    response = client.post(
        "/transactions",
        json={
            "sender_id": str(uuid.uuid4()),
            "receiver_id": receiver["id"],
            "amount": "10.00",
            "currency": "USD",
        },
    )

    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]
    assert enqueued == []


def test_idempotency_key_returns_existing_transaction(
    client: TestClient,
    make_user,
    submit_transaction,
    enqueued: list[uuid.UUID],
) -> None:
    sender = make_user()
    receiver = make_user()
    headers = {"Idempotency-Key": "order-123"}

    first = submit_transaction(sender["id"], receiver["id"], headers=headers)
    second = submit_transaction(sender["id"], receiver["id"], headers=headers)

    assert first["transaction_id"] == second["transaction_id"]
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert len(enqueued) == 1


def test_idempotency_is_scoped_per_sender(
    client: TestClient,
    make_user,
    submit_transaction,
    enqueued: list[uuid.UUID],
) -> None:
    sender_a = make_user()
    sender_b = make_user()
    receiver = make_user()
    headers = {"Idempotency-Key": "shared-key"}

    first = submit_transaction(sender_a["id"], receiver["id"], headers=headers)
    second = submit_transaction(sender_b["id"], receiver["id"], headers=headers)

    assert first["transaction_id"] != second["transaction_id"]
    assert len(enqueued) == 2


def test_broker_failure_still_accepts_transaction(
    client: TestClient,
    make_user,
    submit_transaction,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    def failing_enqueue(transaction_id: uuid.UUID) -> None:
        raise RuntimeError("broker down")

    monkeypatch.setattr(transaction_routes, "enqueue_transaction_evaluation", failing_enqueue)
    sender = make_user()
    receiver = make_user()

    body = submit_transaction(sender["id"], receiver["id"])

    assert body["status"] == "PENDING_REVIEW"
    detail = client.get(f"/transactions/{body['transaction_id']}").json()
    assert detail["status"] == "PENDING_REVIEW"
