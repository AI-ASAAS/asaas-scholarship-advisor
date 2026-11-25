"""FastAPI HTTP router for profile-aware external search & admin DRAFT promotion."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.config import settings
from modules.auth.schemas import AdminPrincipal, StudentPrincipal
from modules.auth.service import require_admin, require_student
from modules.llm.client import AsyncLLMClient, get_llm
from modules.search.schemas import (
    ExternalSearchRunRequest,
    ExternalSearchRunResponse,
    PromoteExternalGrantRequest,
)
from modules.search.service import (
    ProfileExternalSearchService,
    SearchRunBudget,
    cancel_active_run,
)
from utils.rate_limit import RateLimiter, get_client_ip
from utils.url_guard import UnsafeURLError

router = APIRouter(prefix="/api/search", tags=["external-search"])
_service = ProfileExternalSearchService()

student_external_search_limiter = RateLimiter(
    limit=settings.SEARCH_STUDENT_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)
ip_external_search_limiter = RateLimiter(
    limit=settings.SEARCH_STUDENT_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)
global_external_search_limiter = RateLimiter(
    limit=settings.SEARCH_GLOBAL_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)


async def execute_external_search_for_student(
    payload: ExternalSearchRunRequest,
    request: Request,
    student: StudentPrincipal,
    llm: AsyncLLMClient,
    *,
    budget: Optional[SearchRunBudget] = None,
) -> ExternalSearchRunResponse:
    client_ip = get_client_ip(request, settings.trusted_proxies)
    student_external_search_limiter.check(
        f"ext_search:sid:{student.session_id}",
        limit=settings.SEARCH_STUDENT_RATE_LIMIT_PER_HOUR,
        window_seconds=3600,
    )
    ip_external_search_limiter.check(
        f"ext_search:ip:{client_ip}",
        limit=settings.SEARCH_STUDENT_RATE_LIMIT_PER_HOUR,
        window_seconds=3600,
    )
    global_external_search_limiter.check(
        "ext_search:global",
        limit=settings.SEARCH_GLOBAL_RATE_LIMIT_PER_HOUR,
        window_seconds=3600,
    )

    if not (settings.TAVILY_API_KEY or settings.SERPER_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "خدمة البحث الخارجي غير مهيأة حالياً (مفتاح Tavily أو Serper غير مضبوط).",
                "code": "SEARCH_NOT_CONFIGURED",
            },
        )

    return await _service.run_search(
        request=payload,
        llm=llm,
        budget=budget,
        owner_session_id=student.session_id,
    )


@router.post("/external", response_model=ExternalSearchRunResponse)
async def run_profile_external_search(
    payload: ExternalSearchRunRequest,
    request: Request,
    student: StudentPrincipal = Depends(require_student),
    llm: AsyncLLMClient = Depends(get_llm),
) -> ExternalSearchRunResponse:
    return await execute_external_search_for_student(payload, request, student, llm)


@router.post("/external/{run_id}/cancel")
def cancel_profile_external_search(
    run_id: str,
    student: StudentPrincipal = Depends(require_student),
) -> dict:
    cancelled = cancel_active_run(run_id, session_id=student.session_id)
    return {"cancelled": cancelled, "run_id": run_id}


@router.post("/promote", status_code=status.HTTP_201_CREATED)
def promote_external_result_to_draft(
    payload: PromoteExternalGrantRequest,
    _admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    """Admin-only: save a verified external result as DRAFT for human review (never auto-published)."""
    try:
        return _service.promote_to_draft(payload)
    except UnsafeURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": "UNSAFE_URL"},
        ) from exc
