"""Auth endpoints - demo-grade JWT auth so the admin dashboard can be gated."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.schemas.auth import DemoAccount, LoginRequest, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

DEMO_ACCOUNTS = [
    DemoAccount(
        email="admin@campus.edu",
        password="admin123",
        role="admin",
        label="Facilities administrator - full dashboard + resolve rights",
    ),
    DemoAccount(
        email="facilities@campus.edu",
        password="facilities123",
        role="staff",
        label="Campus operations staff - ticket queue access",
    ),
    DemoAccount(
        email="demo@campus.edu",
        password="demo123",
        role="student",
        label="Student reporter - barrier reporting + routing",
    ),
]


@router.post("/login", response_model=TokenOut, summary="Exchange credentials for a JWT")
def login(payload: LoginRequest, db: DbSession) -> TokenOut:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect e-mail or password.",
        )
    token, expires_in = create_access_token(
        subject=user.email, role=user.role, full_name=user.full_name
    )
    return TokenOut(
        access_token=token, expires_in=expires_in, user=UserOut.model_validate(user)
    )


@router.get("/me", response_model=UserOut, summary="Current signed-in profile")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get(
    "/demo-accounts",
    response_model=list[DemoAccount],
    summary="Seeded demo credentials (handy for a live judging session)",
)
def demo_accounts() -> list[DemoAccount]:
    return DEMO_ACCOUNTS


@router.get("/whoami", response_model=dict, summary="Non-failing identity probe")
def whoami(user: OptionalUser) -> dict:
    if user is None:
        return {"authenticated": False, "role": "anonymous"}
    return {"authenticated": True, "role": user.role, "email": user.email}
