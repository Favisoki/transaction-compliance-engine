"""Shared pytest fixtures.

Tests use an in-memory SQLite database and override the FastAPI session
dependency, so no PostgreSQL or Redis instance is required to run them. Celery
publishing is replaced with a recording stub.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.api.routes import admin as admin_routes
from app.api.routes import transactions as transaction_routes
from app.core.config import Settings
from app.main import create_app
from app.models import Base


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        environment="test",
        auto_create_tables=False,
        database_url="sqlite+pysqlite:///:memory:",
        log_level="WARNING",
    )


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    yield factory

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Record task publishes instead of contacting a broker."""

    published: list[uuid.UUID] = []

    def fake_enqueue(transaction_id: uuid.UUID) -> None:
        published.append(transaction_id)

    monkeypatch.setattr(transaction_routes, "enqueue_transaction_evaluation", fake_enqueue)
    monkeypatch.setattr(admin_routes, "enqueue_transaction_evaluation", fake_enqueue)
    return published


@pytest.fixture()
def client(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
    enqueued: list[uuid.UUID],
) -> Iterator[TestClient]:
    app = create_app(test_settings)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def make_user(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _make_user(**overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "email": f"user-{uuid.uuid4().hex[:12]}@example.com",
            "full_name": "Test User",
            "country_code": "US",
            "risk_score": 10,
            "kyc_verified": False,
        }
        payload.update(overrides)
        response = client.post("/users", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _make_user


@pytest.fixture()
def submit_transaction(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _submit(
        sender_id: str,
        receiver_id: str,
        *,
        amount: str = "250.00",
        currency: str = "USD",
        headers: dict[str, str] | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "amount": amount,
            "currency": currency,
        }
        payload.update(overrides)
        response = client.post("/transactions", json=payload, headers=headers or {})
        assert response.status_code == 202, response.text
        return response.json()

    return _submit
