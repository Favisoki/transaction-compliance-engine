"""Tests for user creation and validation."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_create_user_normalises_email_and_country(client: TestClient) -> None:
    response = client.post(
        "/users",
        json={
            "email": "Alice@Example.COM",
            "full_name": "Alice",
            "country_code": "us",
            "risk_score": 25,
            "kyc_verified": True,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["country_code"] == "US"
    assert body["kyc_verified"] is True
    assert body["risk_score"] == 25


def test_duplicate_email_returns_409(client: TestClient) -> None:
    payload = {
        "email": "duplicate@example.com",
        "full_name": "First",
        "country_code": "US",
    }
    assert client.post("/users", json=payload).status_code == 201

    response = client.post(
        "/users",
        json={**payload, "full_name": "Second"},
    )

    assert response.status_code == 409


def test_invalid_country_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/users",
        json={
            "email": "bad-country@example.com",
            "full_name": "Bad Country",
            "country_code": "USA",
        },
    )
    assert response.status_code == 422


def test_risk_score_out_of_range_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/users",
        json={
            "email": "risky@example.com",
            "full_name": "Risky",
            "country_code": "US",
            "risk_score": 101,
        },
    )
    assert response.status_code == 422


def test_unknown_user_returns_404(client: TestClient) -> None:
    response = client.get(f"/users/{uuid.uuid4()}")
    assert response.status_code == 404
