"""Password hashing (PBKDF2-SHA256) and JWT helpers.

Deliberately dependency-light: pbkdf2_hmac ships with the stdlib and PyJWT is
already required for token issuing, so the prototype has no native build step.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

import jwt

from app.core.config import settings
from app.db.models import utcnow

_ITERATIONS = 260_000
_ALGO = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt, expected = stored.split("$")
        if algo != _ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_access_token(
    *, subject: str, role: str, full_name: str | None = None
) -> tuple[str, int]:
    expires_in = settings.jwt_expire_minutes * 60
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "name": full_name,
        "iat": utcnow(),
        "exp": utcnow() + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
