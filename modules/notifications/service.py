"""Notification generator & delivery interface (deterministic, deduplicated, zero LLM)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Protocol
from sqlalchemy.orm import Session

from core.config import settings
from core.models import ApplicationPlan, Grant, GrantStatus, PlanItem, StudentConsent, StudentProfile
from modules.documents.service import _grant_to_eval_dict
from modules.matching.service import evaluate_grant_for_student
from modules.notifications.repository import NotificationsRepository
from modules.plans.generator import local_today
from modules.students.repository import StudentRepository

logger = logging.getLogger(__name__)


class NotificationChannel(Protocol):
    """Future delivery channel interface (D11); only in-app inbox is active in Phase 7."""

    def send(self, *, session_id: str, notification: Dict[str, Any]) -> None: ...


def _deadline_offsets() -> List[int]:
    vals = []
    for part in settings.NOTIFICATIONS_DEADLINE_OFFSETS_RAW.split(","):
        s = part.strip()
        if s.isdigit() and int(s) > 0:
            vals.append(int(s))
    return sorted(set(vals)) or [1, 3, 7, 14]


class NotificationsService:
    """Produces deduplicated in-app notifications from deadlines, reviews, and high-match opt-ins."""

    def generate_plan_alerts(
        self,
        db: Session,
        *,
        reference_date: Optional[date] = None,
    ) -> int:
        today = reference_date or local_today()
        offsets_asc = _deadline_offsets()
        created_count = 0

        plan_rows = (
            db.query(ApplicationPlan.session_id, PlanItem, Grant)
            .join(PlanItem, ApplicationPlan.id == PlanItem.plan_id)
            .join(Grant, PlanItem.grant_id == Grant.id)
            .all()
        )
        for session_id, _plan_item, grant in plan_rows:
            # 1. Expired or unpublished grants in a student's plan
            if grant.status != GrantStatus.PUBLISHED or (grant.deadline is not None and grant.deadline < today):
                st_label = grant.status.value if hasattr(grant.status, "value") else str(grant.status)
                res = NotificationsRepository.create_if_absent(
                    db,
                    session_id=session_id,
                    grant_id=grant.id,
                    kind="plan_grant_unavailable",
                    title=f"تغيّر حالة منحة في خطتك: {grant.title}",
                    body=(
                        f"أصبحت منحة «{grant.title}» منتهية الصلاحية أو غير منشورة حالياً. "
                        f"يُرجى التحقق عبر البوابة الرسمية."
                    ),
                    official_url=grant.official_url,
                    dedupe_key=f"plan_unavailable:{grant.id}:{st_label}",
                )
                if res:
                    created_count += 1
                continue

            # 2. Deadline approaching at 14/7/3/1 days (idempotent across restarts)
            if grant.deadline is not None:
                days_left = (grant.deadline - today).days
                matched_offset = next((off for off in offsets_asc if days_left <= off), None)
                if matched_offset is not None:
                    res = NotificationsRepository.create_if_absent(
                        db,
                        session_id=session_id,
                        grant_id=grant.id,
                        kind=f"deadline_{matched_offset}d",
                        title=f"تنبيه موعد إغلاق ({days_left} يوم متبقٍ): {grant.title}",
                        body=(
                            f"يقترب الموعد النهائي لمنحة «{grant.title}» في {grant.deadline.isoformat()} "
                            f"(المتبقي {days_left} يوم/أيام). راجع قائمة مهامك والبوابة الرسمية قبل التقديم."
                        ),
                        official_url=grant.official_url,
                        dedupe_key=f"deadline_{matched_offset}d:{grant.id}:{grant.deadline.isoformat()}",
                    )
                    if res:
                        created_count += 1

            # 3. Missing required info prompts blocking a good match
            prof = StudentRepository.get_profile(db, session_id)
            if prof is not None:
                eval_res = evaluate_grant_for_student(_grant_to_eval_dict(grant), prof, reference_date=today)
                if eval_res.eligible:
                    unknown_crits = [c for c in eval_res.criteria if c.status == "unknown"]
                    for c in unknown_crits[:1]:
                        res = NotificationsRepository.create_if_absent(
                            db,
                            session_id=session_id,
                            grant_id=grant.id,
                            kind="missing_profile_info",
                            title=f"بيانات ناقصة تؤثر على تقييمك في {grant.title}",
                            body=(
                                f"تنقص بيانات «{c.key}» اللازمة لحساب تطابقك بدقة مع منحة «{grant.title}». "
                                f"{c.reason_ar or 'حدّث ملفك الشخصي لاستكمال النسبة.'}"
                            ),
                            official_url=grant.official_url,
                            dedupe_key=f"missing_info:{c.key}:{grant.id}",
                        )
                        if res:
                            created_count += 1

        return created_count

    def dispatch_approved_change_notifications(self, db: Session, review: Dict[str, Any]) -> int:
        """Notify all students who saved the reviewed grant in their plan."""
        grant_id = int(review["grant_id"])
        grant = db.query(Grant).filter(Grant.id == grant_id).first()
        if grant is None:
            return 0

        sessions = (
            db.query(ApplicationPlan.session_id)
            .join(PlanItem, ApplicationPlan.id == PlanItem.plan_id)
            .filter(PlanItem.grant_id == grant_id)
            .distinct()
            .all()
        )
        count = 0
        for (sid,) in sessions:
            res = NotificationsRepository.create_if_absent(
                db,
                session_id=sid,
                grant_id=grant.id,
                kind="grant_change_approved",
                title=f"تحديث معتمد في منحة داخل خطتك: {grant.title}",
                body=str(review.get("summary_ar") or f"تم اعتماد تعديل في حقل ({review['field_name']}) من قِبل الإدارة."),
                official_url=grant.official_url,
                dedupe_key=f"grant_change_approved:{grant.id}:{review['id']}",
            )
            if res:
                count += 1
        return count

    def dispatch_high_match_for_new_grant(self, db: Session, grant: Grant) -> int:
        """Opt-in only (off by default): notify opted-in students when a high-match grant publishes."""
        if grant.status != GrantStatus.PUBLISHED:
            return 0
        consented = (
            db.query(StudentConsent)
            .filter(StudentConsent.revoked_at.is_(None))
            .all()
        )
        # Keep latest consent per session
        opted_in_sids = set()
        seen_sids = set()
        for c in sorted(consented, key=lambda r: r.id, reverse=True):
            if c.session_id in seen_sids:
                continue
            seen_sids.add(c.session_id)
            if bool((c.scopes_json or {}).get("high_match_alerts", False)):
                opted_in_sids.add(c.session_id)

        if not opted_in_sids:
            return 0

        today = local_today()
        grant_dict = _grant_to_eval_dict(grant)
        count = 0
        for sid in opted_in_sids:
            prof = StudentRepository.get_profile(db, sid)
            if prof is None:
                continue
            eval_res = evaluate_grant_for_student(grant_dict, prof, reference_date=today)
            if eval_res.eligible and eval_res.match_percentage >= settings.NOTIFICATIONS_HIGH_MATCH_THRESHOLD:
                res = NotificationsRepository.create_if_absent(
                    db,
                    session_id=sid,
                    grant_id=grant.id,
                    kind="high_match_new_grant",
                    title=f"منحة جديدة بنسبة تطابق {eval_res.match_percentage}%: {grant.title}",
                    body=(
                        f"نُشرت منحة «{grant.title}» وتطابق ملفك بنسبة {eval_res.match_percentage}%. "
                        "يمكنك مراجعة تفاصيلها وإضافتها لخطتك."
                    ),
                    official_url=grant.official_url,
                    dedupe_key=f"high_match_new:{grant.id}",
                )
                if res:
                    count += 1
        return count
