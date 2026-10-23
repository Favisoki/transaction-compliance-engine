"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text

from app.api.routes import admin, transactions, users
from app.core.config import Settings, get_settings
from app.core.database import engine, init_db
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.auto_create_tables:
            # Auto-create is a development convenience. Production should run
            # migrations and set AUTO_CREATE_TABLES=false.
            init_db()
        logger.info("Starting %s (environment=%s)", settings.app_name, settings.environment)
        yield
        logger.info("Shutting down %s", settings.app_name)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Event-driven transaction ingestion and compliance screening. "
            "Transactions are accepted asynchronously, evaluated by a Celery "
            "worker, and every violation is written to an immutable audit log."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.include_router(transactions.router)
    app.include_router(users.router)
    app.include_router(admin.router)

    @app.get("/", tags=["system"], summary="Service metadata")
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health/live",
        }

    @app.get("/health/live", tags=["system"], summary="Liveness probe")
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["system"], summary="Readiness probe")
    def health_ready() -> dict[str, str]:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("Readiness check failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is not ready",
            ) from exc
        return {"status": "ready"}

    return app


app = create_app()
