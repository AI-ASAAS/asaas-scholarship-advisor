"""FastAPI HTTP router for personalized application plans (Spec Task 8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from core.config import settings
from modules.auth.schemas import StudentPrincipal
from modules.auth.service import require_student
from modules.llm.client import AsyncLLMClient, get_llm
from modules.plans.schemas import (
    PlanAddGrantRequest,
    PlanOverviewResponse,
    PlanSummaryResponse,
    PlanUpdateItemRequest,
)
from modules.plans.service import PlansService
from utils.rate_limit import RateLimiter

router = APIRouter(prefix="/api/plan", tags=["plan"])
_service = PlansService()

plans_rate_limiter = RateLimiter(
    limit=settings.PLANS_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)


def _require_consent(student: StudentPrincipal) -> str:
    if not student.session_id or not student.has_consent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "الموافقة الصريحة على الخصوصية مطلوبة لاستخدام خطة التقديم.",
                "code": "CONSENT_REQUIRED",
            },
        )
    return student.session_id


@router.get("", response_model=PlanOverviewResponse)
def get_application_plan(
    student: StudentPrincipal = Depends(require_student),
) -> PlanOverviewResponse:
    sid = _require_consent(student)
    try:
        return _service.get_plan(session_id=sid)
    except ValueError as exc:
        if str(exc) == "PROFILE_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "يرجى حفظ ملفك الشخصي أولاً لبناء خطة التقديم.", "code": "PROFILE_NOT_FOUND"},
            ) from exc
        raise


@router.post("/items", response_model=PlanOverviewResponse, status_code=status.HTTP_201_CREATED)
def add_grant_to_plan(
    payload: PlanAddGrantRequest,
    student: StudentPrincipal = Depends(require_student),
) -> PlanOverviewResponse:
    sid = _require_consent(student)
    plans_rate_limiter.check(f"plan_write:{sid}", limit=settings.PLANS_RATE_LIMIT_PER_HOUR, window_seconds=3600)
    try:
        return _service.add_grant(session_id=sid, request=payload)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "المنحة غير موجودة أو غير منشورة.", "code": "GRANT_NOT_FOUND"},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "هذه المنحة غير مؤهلة لك حالياً وفق بوابة الأهلية؛ يلزم تأكيد إضافتها مع التحذير.",
                "code": "INELIGIBLE_REQUIRES_CONFIRMATION",
            },
        ) from exc
    except ValueError as exc:
        code = str(exc)
        if code == "PROFILE_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "يرجى حفظ ملفك الشخصي أولاً.", "code": "PROFILE_NOT_FOUND"},
            ) from exc
        if code == "GRANT_EXPIRED":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "لا يمكن إضافة منحة منتهية الصلاحية إلى خطتك.", "code": "GRANT_EXPIRED"},
            ) from exc
        if code == "PLAN_LIMIT_REACHED":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": f"تم بلوغ الحد الأقصى للمنح في الخطة ({settings.PLANS_MAX_ITEMS}).", "code": "PLAN_LIMIT_REACHED"},
            ) from exc
        raise


@router.patch("/items/{item_id}", response_model=PlanOverviewResponse)
def update_plan_item(
    item_id: int,
    payload: PlanUpdateItemRequest,
    student: StudentPrincipal = Depends(require_student),
) -> PlanOverviewResponse:
    sid = _require_consent(student)
    plans_rate_limiter.check(f"plan_write:{sid}", limit=settings.PLANS_RATE_LIMIT_PER_HOUR, window_seconds=3600)
    updated = _service.update_item(session_id=sid, item_id=item_id, request=payload)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "العنصر غير موجود في خطتك.", "code": "PLAN_ITEM_NOT_FOUND"},
        )
    return updated


@router.delete("/items/{item_id}", response_model=PlanOverviewResponse)
def remove_plan_item(
    item_id: int,
    student: StudentPrincipal = Depends(require_student),
) -> PlanOverviewResponse:
    sid = _require_consent(student)
    plans_rate_limiter.check(f"plan_write:{sid}", limit=settings.PLANS_RATE_LIMIT_PER_HOUR, window_seconds=3600)
    updated = _service.remove_item(session_id=sid, item_id=item_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "العنصر غير موجود في خطتك.", "code": "PLAN_ITEM_NOT_FOUND"},
        )
    return updated


@router.get("/calendar.ics")
def download_plan_ics(
    student: StudentPrincipal = Depends(require_student),
) -> Response:
    sid = _require_consent(student)
    ics_text = _service.export_ics(session_id=sid)
    if ics_text is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "خطتك فارغة حالياً؛ أضف منحة لتنزيل التقويم.", "code": "PLAN_EMPTY"},
        )
    return Response(
        content=ics_text.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="asaas-scholarship-plan.ics"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/summary", response_model=PlanSummaryResponse)
async def summarize_application_plan(
    student: StudentPrincipal = Depends(require_student),
    llm: AsyncLLMClient = Depends(get_llm),
) -> PlanSummaryResponse:
    sid = _require_consent(student)
    if getattr(llm, "_configured", False):
        plans_rate_limiter.check(
            f"plan_summary:{sid}",
            limit=settings.PLANS_RATE_LIMIT_PER_HOUR,
            window_seconds=3600,
        )
    try:
        return await _service.summarize_plan(session_id=sid, llm=llm)
    except ValueError as exc:
        if str(exc) == "PROFILE_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "يرجى حفظ ملفك الشخصي أولاً.", "code": "PROFILE_NOT_FOUND"},
            ) from exc
        raise
