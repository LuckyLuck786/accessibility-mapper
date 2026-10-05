"""Auth contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., examples=["admin@campus.edu"])
    password: str = Field(..., min_length=4, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: Literal["student", "staff", "admin"]


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
