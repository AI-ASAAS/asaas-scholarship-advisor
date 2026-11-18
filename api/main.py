"""FastAPI HTTP boundary for Autonomous Discovery & Web Research Sub-Agent.

Follows ASAAS Backend Foundation patterns:
- Lifespan-managed database initialization.
- Standardized {"message": "..."} error responses for the ASAAS frontend.
- Blocking network/agent operations offloaded cleanly via asyncio.to_thread.
- Read-only system readiness status without exposing secrets.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (
    ExternalSearchRequest,
    GrantCountsResponse,
    GrantListResponse,
    GrantResponse,
    IngestRequest,
    SystemStatusResponse,
    TelegramProcessRequest,
    UpdateLogResponse,
)
from core.config import settings
from core.db import get_db, init_db
from core.models import Grant, GrantStatus, UpdateLog
from core.repository import get_grant_by_id, get_grant_by_url, get_top_10_grants, publish
from external_search_sub_agent import search_external_scholarships
from ingestion_sub_agent import ingest
from integrations.telegram_watcher import (
    extract_urls_from_text,
    filter_official_urls,
    process_telegram_posts,
)
from monitor_service import run_monitor_cycle

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Autonomous Discovery & Web Research Sub-Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# ASAAS Standardized Error Handlers ({"message": "..."})
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        {"message": str(error.detail)},
        status_code=error.status_code,
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"][1:])
    msg = f"{field}: {first['msg']}" if field else first["msg"]
    return JSONResponse({"message": msg}, status_code=422)


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
# System Status
# ---------------------------------------------------------------------------

@app.get("/api/system/status", response_model=SystemStatusResponse)
def system_status() -> SystemStatusResponse:
    search_provider = None
    if settings.TAVILY_API_KEY:
        search_provider = "Tavily"
    elif settings.SERPER_API_KEY:
        search_provider = "Serper"

    with get_db() as db:
        counts = _get_counts(db)

    return SystemStatusResponse(
        llm_configured=bool(settings.LLM_API_KEY),
        llm_model=settings.LLM_MODEL,
        search_configured=bool(search_provider),
        search_provider=search_provider,
        telegram_configured=bool(settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH),
        counts=counts,
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
) -> GrantListResponse:
    with get_db() as db:
        query = db.query(Grant)
        if status_filter and status_filter in {"draft", "published", "expired"}:
            query = query.filter(Grant.status == GrantStatus(status_filter))
        grants = query.order_by(Grant.updated_at.desc()).all()
        counts = _get_counts(db)
        return GrantListResponse(
            grants=[GrantResponse(**g.to_dict()) for g in grants],
            counts=counts,
        )


@app.get("/api/grants/{grant_id}", response_model=GrantResponse)
def api_get_grant(grant_id: int) -> GrantResponse:
    with get_db() as db:
        grant = get_grant_by_id(db, grant_id)
        if not grant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="المنحة غير موجودة في قاعدة البيانات.",
            )
        return GrantResponse(**grant.to_dict())


@app.post("/api/grants/{grant_id}/publish", response_model=GrantResponse)
def api_publish_grant(grant_id: int) -> GrantResponse:
    with get_db() as db:
        grant = publish(db, grant_id)
        if not grant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="تعذر العثور على المنحة المطلوب نشرها.",
            )
        return GrantResponse(**grant.to_dict())


# ---------------------------------------------------------------------------
# Task 2: Ingestion Sub-Agent (Agentic Scraper)
# ---------------------------------------------------------------------------

@app.post("/api/agents/ingest", response_model=GrantResponse)
async def api_ingest_url(payload: IngestRequest) -> GrantResponse:
    if not settings.LLM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="مفتاح LLM_API_KEY غير مضبوط في ملف .env؛ أضف المفتاح لتشغيل الاستخلاص الحي.",
        )
    try:
        grant = await asyncio.to_thread(ingest, payload.official_url.strip())
        return GrantResponse(**grant.to_dict())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Ingestion failed for %s", payload.official_url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"تعذر استخلاص الصفحة الرسمية: {type(exc).__name__} - {exc}",
        )


# ---------------------------------------------------------------------------
# Task 4: External Deep Search Sub-Agent (ReAct)
# ---------------------------------------------------------------------------

@app.post("/api/agents/search")
async def api_external_search(payload: ExternalSearchRequest) -> Dict[str, Any]:
    if not (settings.TAVILY_API_KEY or settings.SERPER_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لم يتم ضبط TAVILY_API_KEY أو SERPER_API_KEY في ملف .env لتشغيل البحث الخارجي الحي.",
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
    except Exception as exc:
        logger.exception("External search failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"فشل وكيل البحث الخارجي: {exc}",
        )


# ---------------------------------------------------------------------------
# Task 9: Monitor Service & Audit Logs
# ---------------------------------------------------------------------------

@app.post("/api/agents/monitor/run")
async def api_run_monitor() -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(run_monitor_cycle)
    except Exception as exc:
        logger.exception("Monitor run failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"تعذر إتمام دورة المراقبة: {exc}",
        )


@app.get("/api/agents/monitor/logs", response_model=List[UpdateLogResponse])
def api_monitor_logs(limit: int = Query(default=50, ge=1, le=200)) -> List[UpdateLogResponse]:
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
# Phase 8: Telegram Watcher (Creative Task)
# ---------------------------------------------------------------------------

@app.post("/api/agents/telegram/process")
async def api_telegram_process(payload: TelegramProcessRequest) -> Dict[str, Any]:
    if payload.dry_run or not settings.LLM_API_KEY:
        # Dry-run analysis: extract, filter official domains, and check DB duplicates without LLM calls
        def _dry_run() -> Dict[str, Any]:
            all_urls: List[str] = []
            seen = set()
            for post in payload.posts:
                for url in extract_urls_from_text(post):
                    if url not in seen:
                        seen.add(url)
                        all_urls.append(url)
            trusted, rejected = filter_official_urls(all_urls)
            skipped_existing: List[str] = []
            ready_for_ingest: List[str] = []
            with get_db() as db:
                for u in trusted:
                    if get_grant_by_url(db, u) is not None:
                        skipped_existing.append(u)
                    else:
                        ready_for_ingest.append(u)
            return {
                "mode": "dry_run",
                "posts_processed": len(payload.posts),
                "urls_extracted": len(all_urls),
                "trusted_urls_found": len(trusted),
                "ready_for_ingest": ready_for_ingest,
                "drafts_created": [],
                "skipped_existing": skipped_existing,
                "skipped_untrusted": [{"url": u, "reason": r} for u, r in rejected],
                "errors": [],
                "note": (
                    "وضع الفحص الآمن (Dry Run): تم استخراج الروابط الرسمية وفلترة المجمّعات والمكررات. "
                    + ("" if settings.LLM_API_KEY else "أضف LLM_API_KEY في .env لتحويل الروابط الجديدة تلقائياً إلى مسودات.")
                ),
            }

        return await asyncio.to_thread(_dry_run)

    return await asyncio.to_thread(process_telegram_posts, payload.posts)


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
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
