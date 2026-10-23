"""SQLAlchemy engine and session factory.

The application uses synchronous SQLAlchemy sessions deliberately: Celery
workers are synchronous processes, and a single session style across API and
worker code keeps the persistence layer simple and easy to test.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()

_engine_kwargs: dict[str, object] = {
    "echo": _settings.database_echo,
    "pool_pre_ping": True,
    "future": True,
}

# SQLite (used in tests) does not accept QueuePool sizing arguments.
if not _settings.database_url.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=_settings.database_pool_size,
        max_overflow=_settings.database_pool_max_overflow,
    )

engine = create_engine(_settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Iterator[Session]:
    """Yield a session and always close it."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create tables registered on the declarative metadata.

    This is convenient for local development. Production deployments should
    use a migration tool (e.g. Alembic) with ``AUTO_CREATE_TABLES=false``.
    """

    # Import for the side effect of registering all models on Base.metadata.
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    logger.info("Database schema ensured (create_all)")
