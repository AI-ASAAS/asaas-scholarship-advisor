"""Repository layer for student application plans and pursued grant items."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from core.models import ApplicationPlan, Grant, PlanItem


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _item_to_dict(row: PlanItem) -> Dict[str, Any]:
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "grant_id": row.grant_id,
        "priority_rank": row.priority_rank,
        "status": row.status,
        "deadline_snapshot": row.deadline_snapshot.isoformat() if row.deadline_snapshot else None,
        "checklist": list(row.checklist_json or []),
        "notes": row.notes,
        "allow_ineligible": bool(row.allow_ineligible),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class PlansRepository:
    """Stateless SQLAlchemy repository for `application_plans` and `plan_items`."""

    @staticmethod
    def get_plan_id(db: Session, session_id: str) -> Optional[int]:
        row = db.query(ApplicationPlan).filter(ApplicationPlan.session_id == session_id).first()
        return row.id if row else None

    @staticmethod
    def get_or_create_plan(db: Session, session_id: str) -> int:
        existing = db.query(ApplicationPlan).filter(ApplicationPlan.session_id == session_id).first()
        if existing is not None:
            return existing.id
        now = _utc_now_naive()
        plan = ApplicationPlan(session_id=session_id, created_at=now, updated_at=now)
        db.add(plan)
        db.flush()
        return plan.id

    @staticmethod
    def list_items_with_grants(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
        plan = db.query(ApplicationPlan).filter(ApplicationPlan.session_id == session_id).first()
        if plan is None:
            return None
        rows = (
            db.query(PlanItem, Grant)
            .join(Grant, PlanItem.grant_id == Grant.id)
            .filter(PlanItem.plan_id == plan.id)
            .order_by(PlanItem.priority_rank.asc(), PlanItem.id.asc())
            .all()
        )
        return {
            "plan_id": plan.id,
            "rows": [{"item": _item_to_dict(item), "grant": grant} for item, grant in rows],
        }

    @staticmethod
    def get_item_for_session(db: Session, session_id: str, item_id: int) -> Optional[Dict[str, Any]]:
        row = (
            db.query(PlanItem, Grant)
            .join(ApplicationPlan, PlanItem.plan_id == ApplicationPlan.id)
            .join(Grant, PlanItem.grant_id == Grant.id)
            .filter(ApplicationPlan.session_id == session_id, PlanItem.id == item_id)
            .first()
        )
        if row is None:
            return None
        return {"item": _item_to_dict(row[0]), "grant": row[1]}

    @staticmethod
    def upsert_plan_item(
        db: Session,
        *,
        plan_id: int,
        grant_id: int,
        priority_rank: int,
        deadline_snapshot: Optional[date],
        checklist: List[Dict[str, Any]],
        allow_ineligible: bool,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _utc_now_naive()
        existing = (
            db.query(PlanItem)
            .filter(PlanItem.plan_id == plan_id, PlanItem.grant_id == grant_id)
            .first()
        )
        if existing is None:
            row = PlanItem(
                plan_id=plan_id,
                grant_id=grant_id,
                priority_rank=priority_rank,
                status="planned",
                deadline_snapshot=deadline_snapshot,
                checklist_json=checklist,
                notes=notes,
                allow_ineligible=allow_ineligible,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
            return _item_to_dict(row)

        existing.priority_rank = priority_rank
        existing.deadline_snapshot = deadline_snapshot
        existing.checklist_json = checklist
        existing.allow_ineligible = allow_ineligible
        if notes is not None:
            existing.notes = notes
        existing.updated_at = now
        db.add(existing)
        db.flush()
        return _item_to_dict(existing)

    @staticmethod
    def update_item_fields(
        db: Session,
        *,
        session_id: str,
        item_id: int,
        status: Optional[str] = None,
        notes: Optional[str] = None,
        notes_provided: bool = False,
        checklist: Optional[List[Dict[str, Any]]] = None,
        priority_rank: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        row = (
            db.query(PlanItem)
            .join(ApplicationPlan, PlanItem.plan_id == ApplicationPlan.id)
            .filter(ApplicationPlan.session_id == session_id, PlanItem.id == item_id)
            .first()
        )
        if row is None:
            return None
        if status is not None:
            row.status = status
        if notes_provided:
            row.notes = notes
        if checklist is not None:
            row.checklist_json = checklist
        if priority_rank is not None:
            row.priority_rank = priority_rank
        row.updated_at = _utc_now_naive()
        db.add(row)
        db.flush()
        return _item_to_dict(row)

    @staticmethod
    def update_ranks(db: Session, ranked_ids: List[int]) -> None:
        now = _utc_now_naive()
        for rank, item_id in enumerate(ranked_ids, start=1):
            row = db.query(PlanItem).filter(PlanItem.id == item_id).first()
            if row is not None and row.priority_rank != rank:
                row.priority_rank = rank
                row.updated_at = now
                db.add(row)
        db.flush()

    @staticmethod
    def delete_item(db: Session, session_id: str, item_id: int) -> bool:
        row = (
            db.query(PlanItem)
            .join(ApplicationPlan, PlanItem.plan_id == ApplicationPlan.id)
            .filter(ApplicationPlan.session_id == session_id, PlanItem.id == item_id)
            .first()
        )
        if row is None:
            return False
        db.delete(row)
        db.flush()
        return True
