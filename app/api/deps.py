"""FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_session


def get_db() -> Iterator[Session]:
    yield from get_session()


DbSession = Annotated[Session, Depends(get_db)]
