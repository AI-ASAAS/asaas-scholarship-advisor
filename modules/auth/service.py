"""Authentication and authorization dependencies and session management (D4)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Set
from urllib.parse import urlparse
import uuid

from fastapi import HTTPException, Request, Response, status

from core.config import settings
from core.db import get_db
from core.models import StudentConsent, StudentSession
from modules.auth.schemas import AdminPrincipal, StudentPrincipal
from utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_REVOKED_TOKENS: dict[str, float] = {}
_REVOKED_LOCK = threading.Lock()

login_rate_limiter = RateLimiter(
    limit=settings.LOGIN_RATE_LIMIT,
    window_seconds=settings.LOGIN_RATE_WINDOW_SECONDS,
)


def _effective_admin_key() -> str:
    env_val = os.getenv("ADMIN_API_KEY")
    if env_val is not None:
        return env_val.strip()
    return (settings.ADMIN_API_KEY or "").strip()


def _allow_insecure_local_admin() -> bool:
    if settings.is_production:
        return False
    env_val = os.getenv("ALLOW_INSECURE_LOCAL_ADMIN")
    if env_val is not None:
        return env_val.strip().lower() in {"1", "true", "yes", "on"}
    return settings.ALLOW_INSECURE_LOCAL_ADMIN


def _cookie_name() -> str:
    return "__Host-asaas_admin" if settings.COOKIE_SECURE else "asaas_admin_session"


def _signing_key(admin_secret: str) -> bytes:
    return hashlib.sha256(f"asaas-admin-cookie:{admin_secret}".encode("utf-8")).digest()


def _create_session_token(admin_secret: str, ttl_seconds: int) -> str:
    exp = int(time.time()) + max(60, ttl_seconds)
    nonce = secrets.token_urlsafe(16)
    payload = f"{exp}.{nonce}"
    sig = hmac.new(_signing_key(admin_secret), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_session_token(token: str, admin_secret: str) -> Optional[tuple[str, int]]:
    if not token or not admin_secret:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    exp_str, nonce, provided_sig = parts
    if not exp_str.isdigit() or not nonce or not provided_sig:
        return None
    exp = int(exp_str)
    if exp < int(time.time()):
        return None

    payload = f"{exp_str}.{nonce}"
    expected_sig = hmac.new(
        _signing_key(admin_secret), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        return None

    with _REVOKED_LOCK:
        now = time.time()
        expired_nonces = [k for k, v in _REVOKED_TOKENS.items() if v < now]
        for k in expired_nonces:
            del _REVOKED_TOKENS[k]
        if nonce in _REVOKED_TOKENS:
            return None
    return nonce, exp


def revoke_session_token(token: str) -> None:
    parts = (token or "").split(".")
    if len(parts) == 3 and parts[0].isdigit() and parts[1]:
        with _REVOKED_LOCK:
            _REVOKED_TOKENS[parts[1]] = float(parts[0])


def clear_auth_state_for_tests() -> None:
    """Clear login rate limits and revoked tokens between isolated tests."""
    login_rate_limiter.reset()
    with _REVOKED_LOCK:
        _REVOKED_TOKENS.clear()


def _is_trusted_browser_origin(request: Request) -> bool:
    """Defense-in-depth Origin/Referer and Fetch-Metadata check for cookie-authenticated mutations."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return True
    if (request.headers.get("sec-fetch-site") or "").strip().lower() == "cross-site":
        return False
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    referer = (request.headers.get("referer") or "").strip()
    source_origin = origin
    if not source_origin and referer:
        parsed_ref = urlparse(referer)
        if parsed_ref.scheme and parsed_ref.netloc:
            source_origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
    if not source_origin:
        # Non-browser clients or same-origin tools without Origin header rely on SameSite=Lax
        return True

    allowed: Set[str] = {o.rstrip("/") for o in settings.cors_origins}
    host = (request.headers.get("host") or "").strip()
    if host:
        allowed.add(f"http://{host}")
        allowed.add(f"https://{host}")
    return source_origin in allowed


def is_admin_authenticated(request: Request) -> Optional[AdminPrincipal]:
    """Return AdminPrincipal if valid cookie or X-Admin-Key is present, else None."""
    expected = _effective_admin_key()
    if not expected:
        if _allow_insecure_local_admin():
            return AdminPrincipal(authenticated=True, auth_method="dev_bypass")
        return None

    provided_header = (request.headers.get("X-Admin-Key") or "").strip()
    if provided_header and hmac.compare_digest(
        provided_header.encode("utf-8"), expected.encode("utf-8")
    ):
        return AdminPrincipal(authenticated=True, auth_method="header")

    cookie_token = (request.cookies.get(_cookie_name()) or "").strip()
    if cookie_token and _verify_session_token(cookie_token, expected) is not None:
        if not _is_trusted_browser_origin(request):
            return None
        return AdminPrincipal(authenticated=True, auth_method="cookie")

    return None


def require_admin(request: Request) -> AdminPrincipal:
    """FastAPI dependency enforcing admin authentication on protected endpoints."""
    expected = _effective_admin_key()
    if not expected and not _allow_insecure_local_admin():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "المصادقة مطلوبة للوصول إلى لوحة الإدارة (ADMIN_API_KEY غير مضبوط).",
                "code": "ADMIN_AUTH_REQUIRED",
            },
        )

    principal = is_admin_authenticated(request)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "مطلوب تسجيل دخول المشرف للوصول إلى هذا المورد.",
                "code": "ADMIN_AUTH_REQUIRED",
            },
        )
    return principal


_STUDENT_SESSION_TTL_DAYS = 90


def _student_cookie_name() -> str:
    return "__Host-asaas_student" if settings.COOKIE_SECURE else "asaas_student"


def _hash_student_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def set_student_cookie(response: Response, raw_token: str) -> None:
    """Attach the opaque HttpOnly student session cookie."""
    max_age = _STUDENT_SESSION_TTL_DAYS * 86400
    response.set_cookie(
        key=_student_cookie_name(),
        value=raw_token,
        max_age=max_age,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_student_cookie(response: Response) -> None:
    """Clear the student session cookie on deletion/revocation."""
    response.delete_cookie(
        key=_student_cookie_name(),
        path="/",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )


def issue_student_session(response: Response) -> StudentPrincipal:
    """Create a brand new anonymous server-side student session and set cookie."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_student_token(raw_token)
    session_id = str(uuid.uuid4())
    now = _utc_now_naive()
    expires_at = now + timedelta(days=_STUDENT_SESSION_TTL_DAYS)

    with get_db() as db:
        db.add(
            StudentSession(
                id=session_id,
                token_hash=token_hash,
                created_at=now,
                last_seen_at=now,
                expires_at=expires_at,
            )
        )
        db.flush()

    set_student_cookie(response, raw_token)
    return StudentPrincipal(session_id=session_id, authenticated=True, has_consent=False)


def get_optional_student(request: Request) -> Optional[StudentPrincipal]:
    """Resolve authenticated student principal from HttpOnly cookie, or None."""
    raw_token = (request.cookies.get(_student_cookie_name()) or "").strip()
    if not raw_token:
        return None
    if not _is_trusted_browser_origin(request):
        return None

    token_hash = _hash_student_token(raw_token)
    now = _utc_now_naive()

    with get_db() as db:
        session_row = (
            db.query(StudentSession)
            .filter(StudentSession.token_hash == token_hash)
            .first()
        )
        if session_row is None or session_row.expires_at < now:
            return None

        session_row.last_seen_at = now
        session_row.expires_at = now + timedelta(days=_STUDENT_SESSION_TTL_DAYS)
        db.add(session_row)

        latest_consent = (
            db.query(StudentConsent)
            .filter(
                StudentConsent.session_id == session_row.id,
                StudentConsent.revoked_at.is_(None),
            )
            .order_by(StudentConsent.id.desc())
            .first()
        )
        return StudentPrincipal(
            session_id=session_row.id,
            authenticated=True,
            has_consent=latest_consent is not None,
            consent_version=latest_consent.consent_version if latest_consent else None,
        )


def require_student(request: Request) -> StudentPrincipal:
    """FastAPI dependency enforcing an active server-side student session (D4)."""
    principal = get_optional_student(request)
    if principal is None or not principal.authenticated or not principal.session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "يرجى بدء جلسة طالب صالحة للوصول إلى ملفك الشخصي.",
                "code": "STUDENT_SESSION_REQUIRED",
            },
        )
    return principal


def login_admin(request: Request, response: Response, secret: str) -> AdminPrincipal:
    """Verify admin secret in constant time, enforce rate limit, and issue HttpOnly cookie."""
    client_ip = get_client_ip(request, settings.trusted_proxies)
    login_rate_limiter.check(
        f"admin_login:{client_ip}",
        limit=settings.LOGIN_RATE_LIMIT,
        window_seconds=settings.LOGIN_RATE_WINDOW_SECONDS,
    )

    expected = _effective_admin_key()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "تسجيل دخول المشرف غير مهيأ على الخادم (ADMIN_API_KEY مفقود).",
                "code": "ADMIN_NOT_CONFIGURED",
            },
        )

    provided = secret.strip()
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "مفتاح الإدارة غير صحيح.",
                "code": "INVALID_CREDENTIALS",
            },
        )

    token = _create_session_token(expected, settings.ADMIN_SESSION_TTL_SECONDS)
    response.set_cookie(
        key=_cookie_name(),
        value=token,
        max_age=settings.ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return AdminPrincipal(authenticated=True, auth_method="cookie")


def logout_admin(request: Request, response: Response) -> None:
    """Revoke current admin cookie token and clear the cookie."""
    token = (request.cookies.get(_cookie_name()) or "").strip()
    if token:
        revoke_session_token(token)
    response.delete_cookie(
        key=_cookie_name(),
        path="/",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )
