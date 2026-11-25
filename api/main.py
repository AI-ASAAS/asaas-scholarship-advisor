"""FastAPI HTTP boundary for ASAAS Scholarship Advisor & Discovery API.

Follows ASAAS Backend Foundation patterns:
- Lifespan-managed database initialization and log secret redaction.
- Standardized {"message": "...", "code": "..."} error responses.
- Explicit admin authentication (HttpOnly cookie or X-Admin-Key) and public grant gating.
- Security headers (CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame-ancestors).
- Blocking network/agent operations offloaded cleanly via asyncio.to_thread.
"""

import asyncio
import ipaddress
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (
    ExternalSearchRequest,
    FeaturedRankRequest,
    FetchModelsRequest,
    FetchModelsResponse,
    GrantCountsResponse,
    GrantIngestPreviewResponse,
    GrantListResponse,
    GrantResponse,
    IngestRequest,
    KeyTestResponse,
    ManualGrantCreateRequest,
    ManualGrantUpdateRequest,
    SystemStatusResponse,
    UpdateKeysRequest,
    UpdateLogResponse,
)
from core.config import ENV_PATH, settings
from core.db import get_db, init_db
from core.models import Grant, GrantStatus, UpdateLog
from core.repository import (
    create_manual_grant,
    delete_grant,
    get_grant_by_id,
    get_grant_by_url,
    get_top_10_grants,
    publish,
    set_featured_rank,
    sync_expired_grants,
    update_grant_fields,
)
from external_search_sub_agent import search_external_scholarships
from ingestion_sub_agent import extract_grant_preview, ingest
from modules.assistant.router import router as assistant_router
from modules.auth.router import router as admin_auth_router
from modules.auth.schemas import AdminPrincipal
from modules.auth.service import is_admin_authenticated, require_admin
from modules.documents.router import router as documents_router
from modules.notifications.router import router as notifications_router
from modules.notifications.service import NotificationsService
from modules.plans.router import router as plans_router
from modules.search.router import router as search_router
from modules.llm.client import LLMError, create_async_llm_client_from_settings
from modules.matching.router import router as matching_router
from modules.students.router import router as students_router
from monitor_service import run_monitor_cycle
from utils.logging_redaction import install_log_redaction
from utils.rate_limit import RateLimiter, get_client_ip
from utils.url_guard import UnsafeURLError

logger = logging.getLogger(__name__)
install_log_redaction()

ingest_rate_limiter = RateLimiter(
    limit=settings.INGEST_RATE_LIMIT,
    window_seconds=settings.AGENT_RATE_WINDOW_SECONDS,
)
search_rate_limiter = RateLimiter(
    limit=settings.SEARCH_RATE_LIMIT,
    window_seconds=settings.AGENT_RATE_WINDOW_SECONDS,
)

_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers and appropriate cache policy to every HTTP response."""

    async def dispatch(self, request: Request, call_next) -> Any:
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", _CSP_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")

        path = request.url.path
        if (
            path.startswith("/api/admin")
            or path.startswith("/api/system")
            or path.startswith("/api/students")
            or path.startswith("/api/matches")
            or path.startswith("/api/profile")
            or path.startswith("/api/assistant")
            or path.startswith("/api/documents")
            or path.startswith("/api/plan")
            or path.startswith("/api/notifications")
            or path.startswith("/api/search")
        ):
            response.headers["Cache-Control"] = "no-store"
        elif path == "/theme-init.js":
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_log_redaction()
    init_db()
    # Auto-seed verified Top 10 grants on fresh deployments (empty DB)
    with get_db() as db:
        if db.query(Grant).count() == 0:
            from seed.seed_db import seed_database
            logger.info("Empty database detected on startup — seeding verified Top 10 grants...")
            seed_database(publish_all=True)

    llm_api_key = (settings.LLM_API_KEY or "").strip()
    if llm_api_key.startswith("tvly-"):
        llm_api_key = ""
    llm_http = httpx.AsyncClient(
        base_url=settings.resolved_llm_base_url,
        headers={
            "Authorization": f"Bearer {llm_api_key}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(
            settings.LLM_TIMEOUT_SECONDS,
            connect=min(5.0, settings.LLM_TIMEOUT_SECONDS),
        ),
    )
    app.state.llm_http = llm_http
    app.state.llm = create_async_llm_client_from_settings(llm_http)
    try:
        yield
    finally:
        await llm_http.aclose()


app = FastAPI(
    title="ASAAS Scholarship Advisor & Discovery API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key", "X-Lang", "X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(admin_auth_router)
app.include_router(students_router)
app.include_router(matching_router)
app.include_router(assistant_router)
app.include_router(documents_router)
app.include_router(plans_router)
app.include_router(search_router)
app.include_router(notifications_router)


# ---------------------------------------------------------------------------
# ASAAS Standardized Error Handlers ({"message": "...", "code": "..."})
# ---------------------------------------------------------------------------

def _extract_error_payload(detail: Any, status_code: int) -> Dict[str, str]:
    default_code = f"HTTP_{status_code}"
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "حدث خطأ في الطلب.")
        code = str(detail.get("code") or default_code)
        return {"message": message, "code": code}
    return {"message": str(detail), "code": default_code}


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        _extract_error_payload(error.detail, error.status_code),
        status_code=error.status_code,
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"][1:])
    msg = f"{field}: {first['msg']}" if field else first["msg"]
    return JSONResponse({"message": msg, "code": "VALIDATION_ERROR"}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        {"message": "حدث خطأ داخلي غير متوقع.", "code": "INTERNAL_ERROR"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_counts(db) -> GrantCountsResponse:
    all_grants = db.query(Grant).all()
    published_c = sum(1 for g in all_grants if g.status == GrantStatus.PUBLISHED)
    draft_c = sum(1 for g in all_grants if g.status == GrantStatus.DRAFT)
    expired_c = sum(1 for g in all_grants if g.status == GrantStatus.EXPIRED)
    logs_c = db.query(UpdateLog).count()
    return GrantCountsResponse(
        total=len(all_grants),
        published=published_c,
        draft=draft_c,
        expired=expired_c,
        update_logs=logs_c,
    )


# ---------------------------------------------------------------------------
# System Status & Dev-Only Key Configuration
# ---------------------------------------------------------------------------

def _mask_key(value: Optional[str]) -> Optional[str]:
    """Return a minimal masked hint exposing at most the last 4 characters."""
    if not value or not value.strip():
        return None
    v = value.strip()
    if len(v) <= 8:
        return "••••"
    return f"••••{v[-4:]}"


def _persist_env_key(key: str, value: str) -> None:
    """Persist a single key to local .env ONLY when explicitly permitted in local dev."""
    if not settings.ALLOW_RUNTIME_ENV_WRITE or settings.is_production:
        return
    from dotenv import set_key

    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    set_key(str(ENV_PATH), key, value, quote_mode="never")
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)


_PROVIDER_PRESET_MODELS: Dict[str, List[str]] = {
    "gemini": [
        "gemini-flash-lite-latest",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3.1-flash-lite-preview",
        "gemini-2.0-flash",
    ],
    "openai": [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
        "gpt-4.1",
    ],
    "openrouter": [
        "google/gemma-4-26b-a4b-it:free",
        "google/gemini-2.0-flash-001",
        "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
}

_PROVIDER_BASE_URLS: Dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def _validate_manual_grant_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "يرجى إدخال رابط رسمي صالح يبدأ بـ https:// أو http://.", "code": "INVALID_URL"},
        )
    host = parsed.hostname.lower()
    if host in {"localhost", "ip6-localhost", "ip6-loopback"} or host.endswith((".localhost", ".local", ".internal")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "لا يُسمح بروابط الشبكة المحلية في سجل المنح.", "code": "INVALID_URL"},
        )
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "لا يُسمح بعناوين IP الخاصة في سجل المنح.", "code": "INVALID_URL"},
            )
    except ValueError:
        pass
    return url


def _build_system_status() -> SystemStatusResponse:
    search_provider = None
    if settings.TAVILY_API_KEY:
        search_provider = "Tavily"
    elif settings.SERPER_API_KEY:
        search_provider = "Serper"

    with get_db() as db:
        sync_expired_grants(db)
        counts = _get_counts(db)

    return SystemStatusResponse(
        llm_configured=bool(settings.LLM_API_KEY),
        llm_provider=settings.LLM_PROVIDER or "openrouter",
        llm_model=settings.LLM_MODEL,
        llm_models=settings.resolved_llm_models,
        llm_key_hint=_mask_key(settings.LLM_API_KEY),
        search_configured=bool(search_provider),
        search_provider=search_provider,
        tavily_key_hint=_mask_key(settings.TAVILY_API_KEY),
        serper_key_hint=_mask_key(settings.SERPER_API_KEY),
        dev_keys_enabled=settings.dev_keys_enabled,
        counts=counts,
    )


@app.get("/api/health")
def public_health() -> Dict[str, str]:
    """Minimal unauthenticated liveness/readiness endpoint (exposes zero config or data)."""
    return {"status": "ok"}


@app.get("/api/system/status", response_model=SystemStatusResponse)
def system_status(_admin: AdminPrincipal = Depends(require_admin)) -> SystemStatusResponse:
    return _build_system_status()


@app.post("/api/system/keys", response_model=SystemStatusResponse)
def api_update_keys(
    payload: UpdateKeysRequest,
    _admin: AdminPrincipal = Depends(require_admin),
) -> SystemStatusResponse:
    """Development-only key configuration endpoint (disabled by default and never in prod)."""
    if not settings.dev_keys_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "المسار غير متاح.", "code": "NOT_FOUND"},
        )

    if payload.llm_api_key and payload.llm_api_key.strip().startswith("tvly-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "مفتاح tvly- مخصّص لمحرك بحث Tavily وليس للذكاء الاصطناعي؛ ضعه في حقل Tavily وأدخل مفتاح LLM صحيحاً.",
                "code": "INVALID_KEY_TYPE",
            },
        )

    if payload.llm_provider is not None:
        provider_val = payload.llm_provider.strip().lower()
        settings.LLM_PROVIDER = provider_val
        settings.LLM_BASE_URL = None
        _persist_env_key("LLM_PROVIDER", provider_val)

    field_map = {
        "llm_api_key": ("LLM_API_KEY", "LLM_API_KEY"),
        "llm_model": ("LLM_MODEL", "LLM_MODEL"),
        "tavily_api_key": ("TAVILY_API_KEY", "TAVILY_API_KEY"),
        "serper_api_key": ("SERPER_API_KEY", "SERPER_API_KEY"),
    }

    for field_name, (attr_name, env_key) in field_map.items():
        val = getattr(payload, field_name)
        if val is None:
            continue
        cleaned = val.strip()
        if field_name == "llm_model":
            if not cleaned:
                continue
            settings.LLM_MODEL = cleaned
            settings.LLM_MODELS_RAW = cleaned
            _persist_env_key("LLM_MODEL", cleaned)
            _persist_env_key("LLM_MODELS", cleaned)
            continue
        setattr(settings, attr_name, cleaned or None)
        _persist_env_key(env_key, cleaned)

    return _build_system_status()


@app.post("/api/system/models", response_model=FetchModelsResponse)
async def api_fetch_provider_models(
    payload: FetchModelsRequest,
    _admin: AdminPrincipal = Depends(require_admin),
) -> FetchModelsResponse:
    """List curated or live available models for the selected AI provider."""
    if not settings.dev_keys_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "المسار غير متاح.", "code": "NOT_FOUND"},
        )

    provider = payload.llm_provider.strip().lower()
    presets = list(_PROVIDER_PRESET_MODELS.get(provider, []))
    key_to_use = (payload.llm_api_key or "").strip() or (
        (settings.LLM_API_KEY or "").strip() if settings.LLM_PROVIDER == provider else ""
    )
    base_url = _PROVIDER_BASE_URLS.get(provider)
    if not key_to_use or not base_url:
        return FetchModelsResponse(
            provider=provider,
            models=presets,
            source="presets",
            note="قائمة النماذج المقترحة لهذا المزوّد (أدخل المفتاح لجلب الموديلات المباشرة).",
        )

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {key_to_use}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_items = data.get("data") if isinstance(data, dict) else None
                if isinstance(raw_items, list):
                    live_ids: List[str] = []
                    for item in raw_items:
                        if not isinstance(item, dict) or not item.get("id"):
                            continue
                        mid = str(item["id"]).strip()
                        if mid.startswith("models/"):
                            mid = mid[len("models/") :]
                        if mid and mid not in live_ids:
                            live_ids.append(mid)
                    if live_ids:
                        merged = list(dict.fromkeys([*presets, *live_ids]))[:80]
                        return FetchModelsResponse(
                            provider=provider,
                            models=merged,
                            source="live",
                            note=f"تم جلب {len(live_ids)} نموذجاً متاحاً من {provider}.",
                        )
    except Exception:
        pass

    return FetchModelsResponse(
        provider=provider,
        models=presets,
        source="presets",
        note="تعذّر جلب القائمة المباشرة من المزوّد؛ تم عرض النماذج المعتمدة لهذا المزوّد.",
    )


@app.post("/api/system/test-keys", response_model=KeyTestResponse)
async def api_test_active_keys(
    _admin: AdminPrincipal = Depends(require_admin),
) -> KeyTestResponse:
    """Verify live connectivity of the currently configured LLM key without leaking secrets."""
    provider = (settings.LLM_PROVIDER or "openrouter").strip().lower()
    active_model = settings.resolved_llm_models[0] if settings.resolved_llm_models else settings.LLM_MODEL
    key_hint = _mask_key(settings.LLM_API_KEY)
    search_provider = "Tavily" if settings.TAVILY_API_KEY else ("Serper" if settings.SERPER_API_KEY else None)
    search_msg = (
        f"محرك البحث العميق جاهز عبر {search_provider}."
        if search_provider
        else "مفتاح البحث العميق غير مضاف (يُستخدم فقط لصفحة البحث العميق في الويب عبر Tavily أو Serper)."
    )

    if not (settings.LLM_API_KEY or "").strip():
        return KeyTestResponse(
            llm_ok=False,
            llm_provider=provider,
            llm_model=active_model,
            llm_key_hint=None,
            llm_message="لا يوجد مفتاح ذكاء اصطناعي مضبوط حالياً.",
            search_configured=bool(search_provider),
            search_provider=search_provider,
            search_message=search_msg,
        )

    base_url = _PROVIDER_BASE_URLS.get(provider, settings.resolved_llm_base_url)
    llm_ok = False
    llm_msg = f"تم التحقق من وجود المفتاح ({key_hint}) لمزوّد {provider}."
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY.strip()}"},
            )
            if resp.status_code == 200:
                llm_ok = True
                llm_msg = f"المفتاح النشط ({key_hint}) متصل ويعمل بنجاح مع {provider}."
            elif resp.status_code in (401, 403):
                llm_msg = f"المفتاح الحالي ({key_hint}) مرفوض أو منتهي الصلاحية من {provider} (HTTP {resp.status_code})."
            else:
                llm_msg = f"استجاب المزوّد برمز {resp.status_code} للمفتاح ({key_hint})."
    except Exception:
        llm_msg = f"تعذّر الاتصال اللحظي بمزوّد {provider} للتحقق من ({key_hint})."

    return KeyTestResponse(
        llm_ok=llm_ok,
        llm_provider=provider,
        llm_model=active_model,
        llm_key_hint=key_hint,
        llm_message=llm_msg,
        search_configured=bool(search_provider),
        search_provider=search_provider,
        search_message=search_msg,
    )


# ---------------------------------------------------------------------------
# Task 1: Top 10 & Grant Management
# ---------------------------------------------------------------------------

@app.get("/api/grants/top10", response_model=List[GrantResponse])
def api_get_top10() -> List[GrantResponse]:
    with get_db() as db:
        grants = get_top_10_grants(db, limit=10)
        return [GrantResponse(**g.to_dict()) for g in grants]


@app.get("/api/grants", response_model=GrantListResponse)
def api_list_grants(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantListResponse:
    with get_db() as db:
        sync_expired_grants(db)
        query = db.query(Grant)
        if status_filter and status_filter in {"draft", "published", "expired"}:
            query = query.filter(Grant.status == GrantStatus(status_filter))
        grants = query.order_by(Grant.updated_at.desc()).all()
        counts = _get_counts(db)
        return GrantListResponse(
            grants=[GrantResponse(**g.to_dict()) for g in grants],
            counts=counts,
        )


@app.post("/api/grants", response_model=GrantResponse, status_code=status.HTTP_201_CREATED)
def api_create_manual_grant(
    payload: ManualGrantCreateRequest,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantResponse:
    clean_url = _validate_manual_grant_url(payload.official_url)
    data = payload.model_dump(exclude={"publish_immediately"})
    data["official_url"] = clean_url
    with get_db() as db:
        try:
            grant = create_manual_grant(db, data, publish_immediately=payload.publish_immediately)
        except ValueError as exc:
            if str(exc) == "DUPLICATE_URL":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"message": "يوجد سجل منحة مسجّل مسبقاً بهذا الرابط الرسمي.", "code": "DUPLICATE_URL"},
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": str(exc), "code": "VALIDATION_ERROR"},
            ) from exc
        if grant.status == GrantStatus.PUBLISHED:
            NotificationsService().dispatch_high_match_for_new_grant(db, grant)
        return GrantResponse(**grant.to_dict())


@app.get("/api/grants/{grant_id}", response_model=GrantResponse)
def api_get_grant(grant_id: int, request: Request) -> GrantResponse:
    with get_db() as db:
        sync_expired_grants(db)
        grant = get_grant_by_id(db, grant_id)
        if not grant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "المنحة غير موجودة في قاعدة البيانات.", "code": "GRANT_NOT_FOUND"},
            )
        if grant.status != GrantStatus.PUBLISHED and is_admin_authenticated(request) is None:
            # Never leak draft or expired grants on public endpoints
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "المنحة غير موجودة في قاعدة البيانات.", "code": "GRANT_NOT_FOUND"},
            )
        return GrantResponse(**grant.to_dict())


@app.patch("/api/grants/{grant_id}", response_model=GrantResponse)
def api_update_grant(
    grant_id: int,
    payload: ManualGrantUpdateRequest,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantResponse:
    updates = payload.model_dump(exclude_unset=True)
    if "official_url" in updates and updates["official_url"] is not None:
        updates["official_url"] = _validate_manual_grant_url(updates["official_url"])
    with get_db() as db:
        existing = get_grant_by_id(db, grant_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "المنحة غير موجودة في قاعدة البيانات.", "code": "GRANT_NOT_FOUND"},
            )
        prev_status = existing.status
        try:
            grant = update_grant_fields(db, grant_id, updates)
        except ValueError as exc:
            if str(exc) == "DUPLICATE_URL":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"message": "يوجد سجل منحة آخر بهذا الرابط الرسمي.", "code": "DUPLICATE_URL"},
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": str(exc), "code": "VALIDATION_ERROR"},
            ) from exc
        if grant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "المنحة غير موجودة في قاعدة البيانات.", "code": "GRANT_NOT_FOUND"},
            )
        if prev_status != GrantStatus.PUBLISHED and grant.status == GrantStatus.PUBLISHED:
            NotificationsService().dispatch_high_match_for_new_grant(db, grant)
        return GrantResponse(**grant.to_dict())


@app.delete("/api/grants/{grant_id}")
def api_delete_grant(
    grant_id: int,
    _admin: AdminPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    with get_db() as db:
        if not delete_grant(db, grant_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "المنحة غير موجودة في قاعدة البيانات.", "code": "GRANT_NOT_FOUND"},
            )
        return {"deleted": True, "id": grant_id}


@app.post("/api/grants/{grant_id}/publish", response_model=GrantResponse)
def api_publish_grant(
    grant_id: int,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantResponse:
    with get_db() as db:
        grant = publish(db, grant_id)
        if not grant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "تعذر العثور على المنحة المطلوب نشرها.", "code": "GRANT_NOT_FOUND"},
            )
        NotificationsService().dispatch_high_match_for_new_grant(db, grant)
        return GrantResponse(**grant.to_dict())


@app.patch("/api/grants/{grant_id}/featured", response_model=GrantResponse)
def api_set_grant_featured_rank(
    grant_id: int,
    payload: FeaturedRankRequest,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantResponse:
    with get_db() as db:
        try:
            grant = set_featured_rank(db, grant_id, payload.featured_rank)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": str(exc), "code": "INVALID_FEATURED_RANK"},
            )
        if not grant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "تعذر العثور على المنحة المطلوبة.", "code": "GRANT_NOT_FOUND"},
            )
        return GrantResponse(**grant.to_dict())


# ---------------------------------------------------------------------------
# Task 2: Ingestion Sub-Agent (Agentic Scraper)
# ---------------------------------------------------------------------------

async def _run_ingest_op(url: str, request: Request, fn):
    client_ip = get_client_ip(request, settings.trusted_proxies)
    ingest_rate_limiter.check(
        f"ingest:{client_ip}",
        limit=settings.INGEST_RATE_LIMIT,
        window_seconds=settings.AGENT_RATE_WINDOW_SECONDS,
    )

    if not settings.LLM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "مفتاح الذكاء الاصطناعي (LLM_API_KEY) غير مهيأ على الخادم.",
                "code": "LLM_NOT_CONFIGURED",
            },
        )
    try:
        return await asyncio.to_thread(fn, url.strip())
    except UnsafeURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": "UNSAFE_URL"},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": "INGEST_VALIDATION_ERROR"},
        )
    except LLMError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "خدمة الذكاء الاصطناعي غير متاحة مؤقتاً؛ يرجى المحاولة مرة أخرى بعد قليل.",
                "code": "LLM_UNAVAILABLE",
            },
        )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            msg = "مفتاح الذكاء الاصطناعي غير صالح أو مرفوض من المزوّد."
        elif code == 429:
            msg = "تم تجاوز الحد المجاني لمزوّد الذكاء الاصطناعي مؤقتاً؛ حاول بعد دقيقة."
        elif code == 404:
            msg = "النموذج المحدّد غير متاح لهذا المفتاح."
        else:
            msg = f"رفض المزوّد الطلب (رمز {code})؛ تحقق من الرابط أو الإعدادات."
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": msg, "code": "UPSTREAM_HTTP_ERROR"},
        )
    except Exception:
        logger.exception("Ingestion failed for url=%s", url)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "تعذّر فتح أو استخلاص الصفحة الرسمية؛ تأكد من صلاحية الرابط ومفتاح الذكاء الاصطناعي.",
                "code": "INGEST_FAILED",
            },
        )


@app.post("/api/agents/ingest/preview", response_model=GrantIngestPreviewResponse)
async def api_preview_ingest_url(
    payload: IngestRequest,
    request: Request,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantIngestPreviewResponse:
    """Extract and validate a scholarship page for admin review without persisting to the DB."""
    extracted = await _run_ingest_op(payload.official_url, request, extract_grant_preview)
    raw_deadline = extracted.get("deadline")
    deadline_str = raw_deadline.isoformat() if hasattr(raw_deadline, "isoformat") else raw_deadline
    clean_url = str(extracted.get("official_url") or payload.official_url.strip())
    with get_db() as db:
        existing = get_grant_by_url(db, clean_url) or get_grant_by_url(
            db, payload.official_url.strip()
        )
        existing_id = existing.id if existing is not None else None
        existing_status = existing.status.value if existing is not None else None

    return GrantIngestPreviewResponse(
        title=extracted["title"],
        official_url=clean_url,
        description=extracted.get("description"),
        provider_name=extracted.get("provider_name"),
        host_country=extracted.get("host_country"),
        deadline=deadline_str,
        funding=extracted.get("funding"),
        funding_type=extracted.get("funding_type"),
        accepts_yemeni=extracted.get("accepts_yemeni") or "unclear",
        allowed_degrees=extracted.get("allowed_degrees"),
        fields_of_study=extracted.get("fields_of_study"),
        eligibility=extracted.get("eligibility"),
        criteria=extracted.get("criteria"),
        required_documents=extracted.get("required_documents"),
        how_to_apply=extracted.get("how_to_apply"),
        min_gpa_value=extracted.get("min_gpa_value"),
        min_gpa_scale=extracted.get("min_gpa_scale"),
        min_gpa_normalized_4=extracted.get("min_gpa_normalized_4"),
        evidence=extracted.get("evidence") or {},
        field_verification=extracted.get("field_verification") or {},
        already_exists_id=existing_id,
        already_exists_status=existing_status,
    )


@app.post("/api/agents/ingest", response_model=GrantResponse)
async def api_ingest_url(
    payload: IngestRequest,
    request: Request,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantResponse:
    grant = await _run_ingest_op(payload.official_url, request, ingest)
    return GrantResponse(**grant.to_dict())


# ---------------------------------------------------------------------------
# Task 4: External Deep Search Sub-Agent
# ---------------------------------------------------------------------------

@app.post("/api/agents/search")
async def api_external_search(
    payload: ExternalSearchRequest,
    request: Request,
    _admin: AdminPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    client_ip = get_client_ip(request, settings.trusted_proxies)
    search_rate_limiter.check(
        f"search:{client_ip}",
        limit=settings.SEARCH_RATE_LIMIT,
        window_seconds=settings.AGENT_RATE_WINDOW_SECONDS,
    )

    if not (settings.TAVILY_API_KEY or settings.SERPER_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "مفتاح محرك البحث (TAVILY_API_KEY أو SERPER_API_KEY) غير مهيأ على الخادم.",
                "code": "SEARCH_NOT_CONFIGURED",
            },
        )
    try:
        result = await asyncio.to_thread(
            search_external_scholarships,
            major=payload.major.strip(),
            degree_level=payload.degree_level.strip(),
            target_country=payload.target_country.strip() if payload.target_country else None,
            max_steps=payload.max_steps,
        )
        return result.model_dump()
    except Exception:
        logger.exception("External search failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "تعذّر إتمام البحث الخارجي في الوقت الحالي.",
                "code": "EXTERNAL_SEARCH_FAILED",
            },
        )


# ---------------------------------------------------------------------------
# Task 9: Monitor Service & Audit Logs
# ---------------------------------------------------------------------------

@app.post("/api/agents/monitor/run")
async def api_run_monitor(_admin: AdminPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(run_monitor_cycle)
    except Exception:
        logger.exception("Monitor run failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "تعذّر إتمام دورة المراقبة.", "code": "MONITOR_FAILED"},
        )


@app.get("/api/agents/monitor/logs", response_model=List[UpdateLogResponse])
def api_monitor_logs(
    limit: int = Query(default=50, ge=1, le=200),
    _admin: AdminPrincipal = Depends(require_admin),
) -> List[UpdateLogResponse]:
    with get_db() as db:
        rows = (
            db.query(UpdateLog)
            .order_by(UpdateLog.detected_at.desc())
            .limit(limit)
            .all()
        )
        results: List[UpdateLogResponse] = []
        for row in rows:
            results.append(
                UpdateLogResponse(
                    id=row.id,
                    grant_id=row.grant_id,
                    grant_title=row.grant.title if row.grant else None,
                    field_name=row.field_name,
                    old_value=row.old_value,
                    new_value=row.new_value,
                    detected_at=row.detected_at.isoformat() if row.detected_at else None,
                    notified=row.notified,
                )
            )
        return results


# ---------------------------------------------------------------------------
# Optional Static Frontend Serving (when frontend/dist is built)
# ---------------------------------------------------------------------------

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "المسار غير موجود.", "code": "NOT_FOUND"},
            )
        dist_root = FRONTEND_DIST.resolve()
        if full_path:
            candidate = (dist_root / full_path).resolve()
            if candidate.is_relative_to(dist_root) and candidate.is_file():
                return FileResponse(str(candidate))
        return FileResponse(
            str(dist_root / "index.html"),
            headers={"Cache-Control": "no-cache"},
        )
