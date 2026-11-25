"""Pydantic schemas for admin and student authentication boundaries."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    secret: str = Field(..., min_length=1, max_length=256)


class AdminSessionResponse(BaseModel):
    authenticated: bool


class AdminPrincipal(BaseModel):
    authenticated: bool
    auth_method: str  # "cookie" | "header" | "dev_bypass"


class StudentPrincipal(BaseModel):
    """Student identity contract (D4) bound to opaque HttpOnly server session."""

    session_id: Optional[str] = None
    authenticated: bool = False
    has_consent: bool = False
    consent_version: Optional[str] = None
