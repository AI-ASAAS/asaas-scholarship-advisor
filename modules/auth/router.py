"""Admin authentication routes (login, logout, session check)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from modules.auth.schemas import AdminLoginRequest, AdminSessionResponse
from modules.auth.service import is_admin_authenticated, login_admin, logout_admin

router = APIRouter(prefix="/api/admin", tags=["admin-auth"])


@router.get("/session", response_model=AdminSessionResponse)
def get_admin_session(request: Request) -> AdminSessionResponse:
    """Return whether the caller currently holds a valid admin session."""
    principal = is_admin_authenticated(request)
    return AdminSessionResponse(authenticated=principal is not None)


@router.post("/login", response_model=AdminSessionResponse)
def post_admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
) -> AdminSessionResponse:
    """Authenticate an admin with ADMIN_API_KEY and set an HttpOnly session cookie."""
    login_admin(request, response, payload.secret)
    return AdminSessionResponse(authenticated=True)


@router.post("/logout", response_model=AdminSessionResponse)
def post_admin_logout(request: Request, response: Response) -> AdminSessionResponse:
    """Clear and revoke the admin session cookie."""
    logout_admin(request, response)
    return AdminSessionResponse(authenticated=False)
