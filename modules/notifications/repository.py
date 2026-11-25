"""Repository layer for deduplicated notifications and monitor change-review items."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import Grant, GrantChangeReview, Notification, StudentConsent, UpdateLog


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _notif_to_dict(row: Notification) -> Dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "grant_id": row.grant_id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "official_url": row.official_url,
        "is_read": bool(row.is_read),
        "dedupe_key": row.dedupe_key,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _review_to_dict(row: GrantChangeReview, grant_title: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": row.id,
        "grant_id": row.grant_id,
        "grant_title": grant_title,
        "update_log_id": row.update_log_id,
        "field_name": row.field_name,
        "old_value": row.old_value,
        "new_value": row.new_value,
        "summary_ar": row.summary_ar,
        "status": row.status,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


class NotificationsRepository:
    """Stateless SQLAlchemy repository for student notifications & monitor reviews."""

    @staticmethod
    def create_if_absent(
        db: Session,
        *,
        session_id: str,
        grant_id: Optional[int],
        kind: str,
        title: str,
        body: str,
        official_url: Optional[str],
        dedupe_key: str,
    ) -> Optional[Dict[str, Any]]:
        existing = (
            db.query(Notification)
            .filter(Notification.session_id == session_id, Notification.dedupe_key == dedupe_key)
            .first()
        )
        if existing is not None:
            return None

        row = Notification(
            session_id=session_id,
            grant_id=grant_id,
            kind=kind,
            title=title[:255],
            body=body,
            official_url=official_url,
            is_read=False,
            dedupe_key=dedupe_key[:128],
            created_at=_utc_now_naive(),
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
            return _notif_to_dict(row)
        except IntegrityError:
            return None

    @staticmethod
    def list_for_session(db: Session, session_id: str, limit: int = 50) -> Dict[str, Any]:
        rows = (
            db.query(Notification)
            .filter(Notification.session_id == session_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .all()
        )
        unread = (
            db.query(Notification)
            .filter(Notification.session_id == session_id, Notification.is_read.is_(False))
            .count()
        )
        return {
            "unread_count": int(unread),
            "notifications": [_notif_to_dict(r) for r in rows],
        }

    @staticmethod
    def unread_count(db: Session, session_id: str) -> int:
        return int(
            db.query(Notification)
            .filter(Notification.session_id == session_id, Notification.is_read.is_(False))
            .count()
        )

    @staticmethod
    def mark_read(db: Session, session_id: str, notification_id: int) -> bool:
        row = (
            db.query(Notification)
            .filter(Notification.id == notification_id, Notification.session_id == session_id)
            .first()
        )
        if row is None:
            return False
        if not row.is_read:
            row.is_read = True
            db.add(row)
            db.flush()
        return True

    @staticmethod
    def mark_all_read(db: Session, session_id: str) -> int:
        updated = (
            db.query(Notification)
            .filter(Notification.session_id == session_id, Notification.is_read.is_(False))
            .update({"is_read": True}, synchronize_session=False)
        )
        db.flush()
        return int(updated or 0)

    @staticmethod
    def set_high_match_opt_in(db: Session, session_id: str, enabled: bool) -> bool:
        consent = (
            db.query(StudentConsent)
            .filter(StudentConsent.session_id == session_id, StudentConsent.revoked_at.is_(None))
            .order_by(StudentConsent.id.desc())
            .first()
        )
        if consent is None:
            return False
        scopes = dict(consent.scopes_json or {})
        scopes["high_match_alerts"] = bool(enabled)
        consent.scopes_json = scopes
        db.add(consent)
        db.flush()
        return True

    @staticmethod
    def get_high_match_opt_in(db: Session, session_id: str) -> bool:
        consent = (
            db.query(StudentConsent)
            .filter(StudentConsent.session_id == session_id, StudentConsent.revoked_at.is_(None))
            .order_by(StudentConsent.id.desc())
            .first()
        )
        if consent is None:
            return False
        return bool((consent.scopes_json or {}).get("high_match_alerts", False))

    @staticmethod
    def create_review_item(
        db: Session,
        *,
        grant_id: int,
        update_log_id: Optional[int],
        field_name: str,
        old_value: Optional[str],
        new_value: Optional[str],
        summary_ar: str,
    ) -> Dict[str, Any]:
        # Avoid duplicate pending review for the exact same field + value
        existing = (
            db.query(GrantChangeReview)
            .filter(
                GrantChangeReview.grant_id == grant_id,
                GrantChangeReview.field_name == field_name,
                GrantChangeReview.new_value == new_value,
                GrantChangeReview.status == "pending",
            )
            .first()
        )
        if existing is not None:
            g = db.query(Grant).filter(Grant.id == grant_id).first()
            return _review_to_dict(existing, grant_title=g.title if g else None)

        row = GrantChangeReview(
            grant_id=grant_id,
            update_log_id=update_log_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            summary_ar=summary_ar,
            status="pending",
            created_at=_utc_now_naive(),
        )
        db.add(row)
        db.flush()
        g = db.query(Grant).filter(Grant.id == grant_id).first()
        return _review_to_dict(row, grant_title=g.title if g else None)

    @staticmethod
    def list_reviews(db: Session, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        q = db.query(GrantChangeReview)
        if status_filter in {"pending", "approved", "rejected"}:
            q = q.filter(GrantChangeReview.status == status_filter)
        rows = q.order_by(GrantChangeReview.created_at.desc(), GrantChangeReview.id.desc()).all()
        g_ids = {r.grant_id for r in rows}
        titles: Dict[int, str] = {}
        if g_ids:
            for g in db.query(Grant).filter(Grant.id.in_(g_ids)).all():
                titles[g.id] = g.title
        return [_review_to_dict(r, grant_title=titles.get(r.grant_id)) for r in rows]

    @staticmethod
    def decide_review(
        db: Session,
        review_id: int,
        decision: Literal["approved", "rejected"],
    ) -> Optional[Dict[str, Any]]:
        row = db.query(GrantChangeReview).filter(GrantChangeReview.id == review_id).first()
        if row is None:
            return None
        row.status = decision
        row.reviewed_at = _utc_now_naive()
        db.add(row)

        grant = db.query(Grant).filter(Grant.id == row.grant_id).first()
        if decision == "approved" and grant is not None:
            if row.field_name == "deadline" and row.new_value:
                try:
                    grant.deadline = date.fromisoformat(row.new_value.strip()[:10])
                    grant.updated_at = _utc_now_naive()
                    db.add(grant)
                except ValueError:
                    pass
            elif row.field_name == "content_hash" and row.new_value:
                grant.content_hash = row.new_value.strip()[:64]
                grant.updated_at = _utc_now_naive()
                db.add(grant)
            if row.update_log_id:
                ulog = db.query(UpdateLog).filter(UpdateLog.id == row.update_log_id).first()
                if ulog:
                    ulog.notified = True
                    db.add(ulog)

        db.flush()
        return _review_to_dict(row, grant_title=grant.title if grant else None)
