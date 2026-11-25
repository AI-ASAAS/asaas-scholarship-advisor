"""FastAPI HTTP routers for student notifications inbox and admin monitor review queue."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.db import get_db
from modules.auth.schemas import AdminPrincipal, StudentPrincipal
from modules.auth.service import get_optional_student, require_admin, require_student
from modules.notifications.repository import NotificationsRepository
from modules.notifications.schemas import (
    GrantChangeReviewListResponse,
    GrantChangeReviewResponse,
    NotificationPreferencesRequest,
    NotificationPreferencesResponse,
    NotificationsListResponse,
    UnreadCountResponse,
)
from modules.notifications.service import NotificationsService

router = APIRouter(tags=["notifications"])
_service = NotificationsService()


def _require_consent(student: StudentPrincipal) -> str:
    if not student.session_id or not student.has_consent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "الموافقة الصريحة على الخصوصية مطلوبة لعرض التنبيهات.", "code": "CONSENT_REQUIRED"},
        )
    return student.session_id


@router.get("/api/notifications", response_model=NotificationsListResponse)
def list_my_notifications(
    student: StudentPrincipal = Depends(require_student),
) -> NotificationsListResponse:
    sid = _require_consent(student)
    with get_db() as db:
        _service.generate_plan_alerts(db)
        res = NotificationsRepository.list_for_session(db, sid)
        opt_in = NotificationsRepository.get_high_match_opt_in(db, sid)
    return NotificationsListResponse(
        unread_count=res["unread_count"],
        high_match_alerts_enabled=opt_in,
        notifications=res["notifications"],
    )


@router.get("/api/notifications/unread-count", response_model=UnreadCountResponse)
def get_unread_count(request: Request) -> UnreadCountResponse:
    student = get_optional_student(request)
    if not student or not student.session_id or not student.has_consent:
        return UnreadCountResponse(unread_count=0)
    with get_db() as db:
        count = NotificationsRepository.unread_count(db, student.session_id)
    return UnreadCountResponse(unread_count=count)


@router.post("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    student: StudentPrincipal = Depends(require_student),
) -> dict:
    sid = _require_consent(student)
    with get_db() as db:
        ok = NotificationsRepository.mark_read(db, sid, notification_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "التنبيه غير موجود.", "code": "NOTIFICATION_NOT_FOUND"},
        )
    return {"ok": True, "id": notification_id}


@router.post("/api/notifications/read-all")
def mark_all_notifications_read(
    student: StudentPrincipal = Depends(require_student),
) -> dict:
    sid = _require_consent(student)
    with get_db() as db:
        updated = NotificationsRepository.mark_all_read(db, sid)
    return {"ok": True, "marked_read": updated}


@router.post("/api/notifications/preferences", response_model=NotificationPreferencesResponse)
def update_notification_preferences(
    payload: NotificationPreferencesRequest,
    student: StudentPrincipal = Depends(require_student),
) -> NotificationPreferencesResponse:
    sid = _require_consent(student)
    with get_db() as db:
        NotificationsRepository.set_high_match_opt_in(db, sid, payload.high_match_alerts)
    return NotificationPreferencesResponse(high_match_alerts=payload.high_match_alerts)


# ---------------------------------------------------------------------------
# Admin Change-Review Queue (Spec Part B #1)
# ---------------------------------------------------------------------------

@router.get("/api/admin/monitor/reviews", response_model=GrantChangeReviewListResponse)
def list_monitor_reviews(
    status_filter: Optional[str] = Query(default=None),
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantChangeReviewListResponse:
    with get_db() as db:
        rows = NotificationsRepository.list_reviews(db, status_filter=status_filter)
    return GrantChangeReviewListResponse(count=len(rows), reviews=rows)


@router.post("/api/admin/monitor/reviews/{review_id}/approve", response_model=GrantChangeReviewResponse)
def approve_monitor_review(
    review_id: int,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantChangeReviewResponse:
    with get_db() as db:
        decided = NotificationsRepository.decide_review(db, review_id, "approved")
        if decided is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "عنصر المراجعة غير موجود.", "code": "REVIEW_NOT_FOUND"},
            )
        _service.dispatch_approved_change_notifications(db, decided)
    return GrantChangeReviewResponse(**decided)


@router.post("/api/admin/monitor/reviews/{review_id}/reject", response_model=GrantChangeReviewResponse)
def reject_monitor_review(
    review_id: int,
    _admin: AdminPrincipal = Depends(require_admin),
) -> GrantChangeReviewResponse:
    with get_db() as db:
        decided = NotificationsRepository.decide_review(db, review_id, "rejected")
        if decided is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "عنصر المراجعة غير موجود.", "code": "REVIEW_NOT_FOUND"},
            )
    return GrantChangeReviewResponse(**decided)
