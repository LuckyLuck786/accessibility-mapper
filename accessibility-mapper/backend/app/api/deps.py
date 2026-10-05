"""Shared FastAPI dependencies: auth, admin token, graph freshness, rate limits.

Authentication model (Phase 0)
-------------------------------
* **Public read-only**: map, routing, Ghost Space views. No credentials needed.
* **Public mutations** (report, check-in, reclaim, clock writes): open to
  anonymous callers but rate limited, and a public barrier report always lands
  ``unverified`` (see ``submit_report``).
* **Admin actions** (resolve/reopen/verify barrier, ticket moves, Ghost Space
  override, demo reset, seed): require ``X-Admin-Token`` matching the
  ``ADMIN_TOKEN`` env var, **or** a JWT belonging to an ``admin`` user. In
  production (``ENVIRONMENT=production``) the token is mandatory; locally the
  JWT path is enough so the demo works without pasting a secret around.

Every DB session yielded from :func:`FreshDb` has already checked
``graph_version`` and rebuilt the in-memory NetworkX graph if it moved. That is
what makes a warm serverless instance safe: it never serves a routing decision
from a graph that another instance has since invalidated.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.security import decode_access_token
from app.db.models import User
from app.services.graph_service import graph_service

bearer = HTTPBearer(auto_error=False, description="JWT issued by /auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def FreshDb() -> Iterator[Session]:  # noqa: N802 - dependency factory
    """Yield a session whose graph has been refreshed against ``graph_version``.

    Used by every endpoint that reads the routing graph. One indexed primary-key
    lookup per request is far cheaper than rebuilding the graph per request, and
    far cheaper than a wrong answer.
    """
    db = SessionLocal()
    try:
        graph_service.ensure_fresh(db)
        yield db
    finally:
        db.close()


FreshDbSession = Annotated[Session, Depends(FreshDb)]


# -----------------------------------------------------------------------
# JWT identity
# -----------------------------------------------------------------------
def _user_from_credentials(
    credentials: HTTPAuthorizationCredentials | None, db: Session
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        return None
    subject = payload.get("sub")
    if not subject:
        return None
    return db.query(User).filter(User.email == subject).one_or_none()


def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: DbSession,
) -> User | None:
    """Citizens can report anonymously; admins get extra powers when signed in."""
    return _user_from_credentials(credentials, db)


def get_current_user(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue (POST /api/v1/auth/login).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Facilities dashboard actions require the admin role.",
        )
    return user


def require_staff(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in ("admin", "staff"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires campus staff or admin privileges.",
        )
    return user


def admin_token_ok(token: str | None) -> bool:
    """Constant-time comparison of the ``X-Admin-Token`` header against env."""
    if not token or not settings.admin_token:
        return False
    return hmac.compare_digest(token.strip(), settings.admin_token)


def admin_guard(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: DbSession,
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> User | None:
    """Gate for every mutating admin route.

    Accepts ``X-Admin-Token`` (the deployment's real gate) or an admin JWT (the
    local demo's convenience). When ``ADMIN_TOKEN`` is unset *and* the app is
    not in production, an admin JWT alone is enough.
    """
    if admin_token_ok(x_admin_token):
        return None

    user = _user_from_credentials(credentials, db)

    # Production: the token is the only way in. This is the honest default for
    # a public deployment - a JWT for a seeded demo password is not security.
    if settings.admin_token:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin actions require a valid X-Admin-Token header.",
                headers={"WWW-Authenticate": "X-Admin-Token"},
            )
        # Local/test: an admin JWT still works so the dashboard is usable.
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Provide X-Admin-Token, or sign in with an admin account."
                ),
                headers={"WWW-Authenticate": "X-Admin-Token"},
            )
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Facilities dashboard actions require the admin role.",
            )
        return user

    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin actions are disabled: the server has no ADMIN_TOKEN "
                "configured. Set ADMIN_TOKEN in the deployment environment."
            ),
        )

    # Demo mode (no ADMIN_TOKEN, not production): open, but attributed.
    return user


def require_admin_mutation(
    request: Request,
    guard: Annotated[User | None, Depends(admin_guard)],
) -> User | None:
    """Alias kept for readability at mutating call sites."""
    return guard


def reporter_label(request: Request, user: User | None) -> str:
    """Identify a reporter without storing anything that identifies a person.

    Signed-in users are labelled by e-mail (they opted in). Anonymous reports
    are labelled by a salted hash of the client IP so repeat abuse is still
    detectable but no raw address is persisted.
    """
    if user is not None:
        return user.email
    client = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(f"{settings.jwt_secret}:{client}".encode()).hexdigest()[:12]
    return f"anon-{digest}"


def enforce_report_quota(request: Request, reporter: str | None) -> dict:
    """Per-client report quota, counted in the database. Raises 429 when spent."""
    from app.services.media_service import client_key, report_quota

    with SessionLocal() as db:
        key = client_key(
            request.client.host if request.client else None, reporter
        )
        state = report_quota(db, key)
        db.commit()
    if not state["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=state["reason"],
            headers={
                "Retry-After": "3600",
                "X-RateLimit-Limit-Hour": str(settings.max_reports_per_hour),
                "X-RateLimit-Remaining-Hour": "0",
            },
        )
    return state


OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
AdminUser = Annotated[User, Depends(require_admin)]
StaffUser = Annotated[User, Depends(require_staff)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminGuard = Annotated[User | None, Depends(admin_guard)]