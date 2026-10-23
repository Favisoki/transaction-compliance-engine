"""User endpoints.

Kept deliberately small: users exist so transactions have persistent parties
with KYC state and a jurisdiction.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer profile",
    responses={409: {"description": "Email already registered"}},
)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        country_code=payload.country_code,
        risk_score=payload.risk_score,
        kyc_verified=payload.kyc_verified,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        ) from exc
    db.refresh(user)
    return user


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Fetch a customer profile",
    responses={404: {"description": "User not found"}},
)
def get_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
