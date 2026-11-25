"""FastAPI router for deterministic scholarship matching and profile analysis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.config import settings
from core.db import get_db
from core.models import Grant, GrantStatus
from modules.auth.schemas import StudentPrincipal
from modules.auth.service import require_student
from modules.llm.client import AsyncLLMClient, get_llm
from modules.matching.analysis import generate_profile_analysis
from modules.matching.schemas import MatchesListResponse, ProfileAnalysisResponse
from modules.matching.service import compute_matches_for_student, compute_matches_from_db
from modules.search.router import execute_external_search_for_student
from modules.search.schemas import (
    ExternalSearchMatchesRequest,
    ExternalSearchRunRequest,
    ExternalSearchRunResponse,
)
from modules.search.service import SearchRunBudget
from modules.students.repository import StudentRepository
from utils.rate_limit import RateLimiter, get_client_ip

router = APIRouter(tags=["matching"])

matches_rate_limiter = RateLimiter(limit=60, window_seconds=3600)
analysis_rate_limiter = RateLimiter(limit=20, window_seconds=3600)


def _load_student_dict_or_404(session_id: str) -> dict:
    with get_db() as db:
        record = StudentRepository.get_profile(db, session_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "يرجى إكمال وحفظ ملفك الشخصي أولاً لحساب نسبة التطابق.",
                    "code": "PROFILE_NOT_FOUND",
                },
            )
        return dict(record)


@router.get("/api/matches", response_model=MatchesListResponse)
def get_student_matches(
    request: Request,
    student: StudentPrincipal = Depends(require_student),
) -> MatchesListResponse:
    client_ip = get_client_ip(request, settings.trusted_proxies)
    matches_rate_limiter.check(f"matches:{student.session_id}:{client_ip}", limit=60, window_seconds=3600)
    profile = _load_student_dict_or_404(student.session_id)  # type: ignore[arg-type]
    return compute_matches_from_db(profile)


@router.post("/api/profile/analysis", response_model=ProfileAnalysisResponse)
async def analyze_student_profile(
    request: Request,
    student: StudentPrincipal = Depends(require_student),
    llm: AsyncLLMClient = Depends(get_llm),
) -> ProfileAnalysisResponse:
    client_ip = get_client_ip(request, settings.trusted_proxies)
    analysis_rate_limiter.check(
        f"analysis:{student.session_id}:{client_ip}",
        limit=20,
        window_seconds=3600,
    )
    profile = _load_student_dict_or_404(student.session_id)  # type: ignore[arg-type]

    with get_db() as db:
        published_rows = db.query(Grant).filter(Grant.status == GrantStatus.PUBLISHED).all()
        grant_dicts = [g.to_dict() for g in published_rows]

    grants_by_id = {int(g["id"]): g for g in grant_dicts}
    matches = compute_matches_for_student(profile, grant_dicts)
    effective_llm = llm if getattr(llm, "_configured", False) else None
    return await generate_profile_analysis(
        profile,
        matches,
        grants_by_id=grants_by_id,
        llm_client=effective_llm,
    )


@router.post("/api/matches/external", response_model=ExternalSearchRunResponse)
async def search_external_matches_for_profile(
    payload: ExternalSearchMatchesRequest,
    request: Request,
    student: StudentPrincipal = Depends(require_student),
    llm: AsyncLLMClient = Depends(get_llm),
) -> ExternalSearchRunResponse:
    """Discover Top 3–5 matching scholarships outside ASAAS from the student's saved profile."""
    profile = _load_student_dict_or_404(student.session_id)  # type: ignore[arg-type]
    raw_targets = [str(f).strip() for f in (profile.get("target_fields") or []) if str(f).strip()]
    major = str(profile.get("major") or "").strip() or (raw_targets[0] if raw_targets else "")
    if len(major) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "يرجى إضافة تخصصك الدراسي في الملف الشخصي أولاً للبحث عن منح مطابقة خارج المنصة.",
                "code": "MISSING_MAJOR",
            },
        )

    degree = str(profile.get("target_degree") or "master")
    if degree not in {"high_school", "bachelor", "master", "phd"}:
        degree = "master"

    run_req = ExternalSearchRunRequest(
        run_id=payload.run_id,
        nationality=str(profile.get("nationality") or "YE"),
        target_degree=degree,  # type: ignore[arg-type]
        major=major[:160],
        target_countries=list(profile.get("target_countries") or [])[:10],
        target_fields=raw_targets[:10],
        gpa_raw=profile.get("gpa_raw"),
        gpa_scale=profile.get("gpa_scale"),
        languages=list(profile.get("languages") or [])[:6],
        use_cache=payload.use_cache,
        exclude_platform_grants=True,
        only_eligible=True,
        max_results=payload.limit,
    )
    budget = SearchRunBudget(
        max_queries=3,
        max_pages=10,
        max_steps=40,
        wall_clock_seconds=max(settings.SEARCH_WALL_CLOCK_SECONDS, 55.0),
        max_tokens=max(settings.SEARCH_MAX_TOKENS_PER_RUN, 8000),
    )
    return await execute_external_search_for_student(
        run_req,
        request,
        student,
        llm,
        budget=budget,
    )
