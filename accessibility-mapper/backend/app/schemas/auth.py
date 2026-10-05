"""Auth contracts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Deliberately a plain `str` plus a shape check rather than pydantic's
# `EmailStr`. `EmailStr` imports `email-validator` at module import time, which
# is one more compiled dependency in an already size-constrained serverless
# bundle, for a field that only ever appears in a demo login form. We cannot
# check deliverability from here, so this checks shape only.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def _clean_email(value: str) -> str:
    candidate = value.strip().lower()
    if not _EMAIL_RE.match(candidate):
        raise ValueError("value is not a valid email address")
    return candidate


class LoginRequest(BaseModel):
    email: str = Field(..., examples=["admin@campus.edu"])
    password: str = Field(..., min_length=4, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _clean_email(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Literal["student", "staff", "admin"]

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _clean_email(value)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class DemoAccount(BaseModel):
    email: str
    password: str
    role: str
    label: str
