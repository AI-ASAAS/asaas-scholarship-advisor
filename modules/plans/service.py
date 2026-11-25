"""Service layer for personalized application plan orchestration & optional AI phrasing."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence
from sqlalchemy.orm import Session

from core.config import settings
from core.db import get_db
from core.models import Grant, GrantStatus
from core.repository import get_grant_by_id
from modules.documents.service import _grant_to_eval_dict, _strip_pii_from_profile
from modules.llm.client import AsyncLLMClient, LLMError
from modules.llm.prompts import load_prompt
from modules.matching.service import evaluate_grant_for_student
from modules.plans.generator import (
    build_backward_milestones,
    build_grant_checklist,
    build_ics_calendar,
    classify_deadline_urgency,
    detect_deadline_conflicts,
    local_today,
    sort_plan_entries,
)
from modules.plans.repository import PlansRepository
from modules.plans.schemas import (
    LLMPlanSummaryOutput,
    PlanAddGrantRequest,
    PlanGrantItemResponse,
    PlanOverviewResponse,
    PlanSummaryResponse,
    PlanUpdateItemRequest,
)
from modules.students.service import StudentService

logger = logging.getLogger(__name__)


def _compute_progress(checklist: Sequence[Dict[str, Any]]) -> float:
    actionable = [c for c in checklist if c.get("category") != "missing_official"] or list(checklist)
    if not actionable:
        return 0.0
    done = sum(1 for c in actionable if c.get("status") == "done")
    in_prog = sum(1 for c in actionable if c.get("status") == "in_progress")
    return round(((done + 0.5 * in_prog) / len(actionable)) * 100.0, 1)


class PlansService:
    """Orchestrates deterministic plan creation, progress updates, .ics export, and optional summary."""

    def add_grant(
        self,
        *,
        session_id: str,
        request: PlanAddGrantRequest,
        now_utc: Optional[datetime] = None,
    ) -> PlanOverviewResponse:
        profile = StudentService().get_profile(session_id)
        if profile is None:
            raise ValueError("PROFILE_NOT_FOUND")
        prof_dict = profile.model_dump()
        today = local_today(now_utc=now_utc)

        with get_db() as db:
            grant = get_grant_by_id(db, request.grant_id)
            if grant is None or grant.status == GrantStatus.DRAFT:
                raise LookupError("GRANT_NOT_FOUND")
            if grant.status == GrantStatus.EXPIRED or (grant.deadline is not None and grant.deadline < today):
                raise ValueError("GRANT_EXPIRED")

            eval_res = evaluate_grant_for_student(_grant_to_eval_dict(grant), prof_dict, reference_date=today)
            if not eval_res.eligible and not request.allow_ineligible:
                raise PermissionError("INELIGIBLE_REQUIRES_CONFIRMATION")

            plan_id = PlansRepository.get_or_create_plan(db, session_id)
            existing_data = PlansRepository.list_items_with_grants(db, session_id)
            current_rows = existing_data["rows"] if existing_data else []
            already_present = any(r["item"]["grant_id"] == request.grant_id for r in current_rows)
            if not already_present and len(current_rows) >= settings.PLANS_MAX_ITEMS:
                raise ValueError("PLAN_LIMIT_REACHED")

            existing_checklist = next(
                (r["item"]["checklist"] for r in current_rows if r["item"]["grant_id"] == request.grant_id),
                [],
            )
            checklist = build_grant_checklist(
                profile=prof_dict,
                grant=_grant_to_eval_dict(grant),
                existing_items=existing_checklist,
                reference_date=today,
            )
            PlansRepository.upsert_plan_item(
                db,
                plan_id=plan_id,
                grant_id=grant.id,
                priority_rank=len(current_rows) + 1,
                deadline_snapshot=grant.deadline,
                checklist=[c.model_dump() for c in checklist],
                allow_ineligible=(not eval_res.eligible and request.allow_ineligible),
                notes=request.notes,
            )

        return self.get_plan(session_id=session_id, now_utc=now_utc)

    def get_plan(
        self,
        *,
        session_id: str,
        now_utc: Optional[datetime] = None,
    ) -> PlanOverviewResponse:
        profile = StudentService().get_profile(session_id)
        if profile is None:
            raise ValueError("PROFILE_NOT_FOUND")
        prof_dict = profile.model_dump()
        today = local_today(now_utc=now_utc)

        with get_db() as db:
            data = PlansRepository.list_items_with_grants(db, session_id)
            if data is None or not data["rows"]:
                return PlanOverviewResponse(
                    plan_id=data["plan_id"] if data else None,
                    timezone=settings.PLANS_TIMEZONE,
                    as_of_date=today.isoformat(),
                    total_grants=0,
                    overall_progress_percentage=0.0,
                    conflicts=[],
                    items=[],
                )

            plan_id = data["plan_id"]
            computed_entries: List[Dict[str, Any]] = []
            for entry in data["rows"]:
                item_row = entry["item"]
                grant_obj: Grant = entry["grant"]
                grant_dict = _grant_to_eval_dict(grant_obj)
                eval_res = evaluate_grant_for_student(grant_dict, prof_dict, reference_date=today)
                fresh_checklist = build_grant_checklist(
                    profile=prof_dict,
                    grant=grant_dict,
                    existing_items=item_row["checklist"],
                    reference_date=today,
                )
                checklist_dicts = [c.model_dump() for c in fresh_checklist]
                # Persist fresh checklist if grant data or profile gaps changed
                if checklist_dicts != item_row["checklist"]:
                    PlansRepository.update_item_fields(
                        db, session_id=session_id, item_id=item_row["id"], checklist=checklist_dicts
                    )

                dl_date: Optional[date] = grant_obj.deadline
                days_left, urgency = classify_deadline_urgency(dl_date, today=today)
                milestones = build_backward_milestones(dl_date, today=today)
                inelig_ar = None
                inelig_en = None
                if not eval_res.eligible:
                    inelig_ar = "; ".join(d.reason_ar for d in eval_res.disqualifiers) or "غير مستوفٍ لبوابة الأهلية"
                    inelig_en = "; ".join(d.reason_en for d in eval_res.disqualifiers) or "Ineligible (hard gate failed)"

                computed_entries.append(
                    {
                        "id": item_row["id"],
                        "grant_id": grant_obj.id,
                        "title": grant_obj.title,
                        "official_url": grant_obj.official_url,
                        "host_country": grant_obj.host_country,
                        "funding_type": grant_obj.funding_type,
                        "status": item_row["status"],
                        "eligible": eval_res.eligible,
                        "ineligible_warning_ar": inelig_ar,
                        "ineligible_warning_en": inelig_en,
                        "match_percentage": eval_res.match_percentage,
                        "coverage_percentage": eval_res.coverage_percentage,
                        "deadline_date": dl_date,
                        "deadline": dl_date.isoformat() if dl_date else None,
                        "days_remaining": days_left,
                        "urgency": urgency,
                        "progress_percentage": _compute_progress(checklist_dicts),
                        "how_to_apply_text": grant_obj.how_to_apply,
                        "how_to_apply_evidence": (grant_obj.evidence or {}).get("how_to_apply"),
                        "checklist": fresh_checklist,
                        "milestones": milestones,
                        "notes": item_row["notes"],
                    }
                )

            ordered = sort_plan_entries(computed_entries)
            PlansRepository.update_ranks(db, [e["id"] for e in ordered])

            items_out: List[PlanGrantItemResponse] = []
            dated_for_conflicts = []
            for rank, e in enumerate(ordered, start=1):
                if isinstance(e["deadline_date"], date):
                    dated_for_conflicts.append((e["grant_id"], e["title"], e["deadline_date"]))
                items_out.append(
                    PlanGrantItemResponse(
                        id=e["id"],
                        grant_id=e["grant_id"],
                        title=e["title"],
                        official_url=e["official_url"],
                        host_country=e["host_country"],
                        funding_type=e["funding_type"],
                        priority_rank=rank,
                        status=e["status"],
                        eligible=e["eligible"],
                        ineligible_warning_ar=e["ineligible_warning_ar"],
                        ineligible_warning_en=e["ineligible_warning_en"],
                        match_percentage=e["match_percentage"],
                        coverage_percentage=e["coverage_percentage"],
                        deadline=e["deadline"],
                        days_remaining=e["days_remaining"],
                        urgency=e["urgency"],
                        progress_percentage=e["progress_percentage"],
                        how_to_apply_text=e["how_to_apply_text"],
                        how_to_apply_evidence=e["how_to_apply_evidence"],
                        checklist=e["checklist"],
                        milestones=e["milestones"],
                        notes=e["notes"],
                    )
                )

            conflicts = detect_deadline_conflicts(dated_for_conflicts)
            avg_progress = (
                round(sum(it.progress_percentage for it in items_out) / len(items_out), 1)
                if items_out
                else 0.0
            )
            return PlanOverviewResponse(
                plan_id=plan_id,
                timezone=settings.PLANS_TIMEZONE,
                as_of_date=today.isoformat(),
                total_grants=len(items_out),
                overall_progress_percentage=avg_progress,
                conflicts=conflicts,
                items=items_out,
            )

    def update_item(
        self,
        *,
        session_id: str,
        item_id: int,
        request: PlanUpdateItemRequest,
        now_utc: Optional[datetime] = None,
    ) -> Optional[PlanOverviewResponse]:
        with get_db() as db:
            found = PlansRepository.get_item_for_session(db, session_id, item_id)
            if found is None:
                return None
            cur_checklist = list(found["item"]["checklist"])
            if request.checklist_updates:
                updates_map = {u.id: u.status for u in request.checklist_updates}
                for c in cur_checklist:
                    if c.get("id") in updates_map:
                        c["status"] = updates_map[c["id"]]

            notes_provided = "notes" in request.model_fields_set
            PlansRepository.update_item_fields(
                db,
                session_id=session_id,
                item_id=item_id,
                status=request.status,
                notes=request.notes,
                notes_provided=notes_provided,
                checklist=cur_checklist if request.checklist_updates else None,
            )

        return self.get_plan(session_id=session_id, now_utc=now_utc)

    def remove_item(
        self,
        *,
        session_id: str,
        item_id: int,
        now_utc: Optional[datetime] = None,
    ) -> Optional[PlanOverviewResponse]:
        with get_db() as db:
            ok = PlansRepository.delete_item(db, session_id, item_id)
            if not ok:
                return None
        return self.get_plan(session_id=session_id, now_utc=now_utc)

    def export_ics(
        self,
        *,
        session_id: str,
        now_utc: Optional[datetime] = None,
    ) -> Optional[str]:
        plan = self.get_plan(session_id=session_id, now_utc=now_utc)
        if not plan.items:
            return None
        raw_items = [
            {
                "grant_id": it.grant_id,
                "title": it.title,
                "official_url": it.official_url,
                "priority_rank": it.priority_rank,
                "match_percentage": it.match_percentage,
                "deadline_date": date.fromisoformat(it.deadline) if it.deadline else None,
            }
            for it in plan.items
        ]
        return build_ics_calendar(plan_id=plan.plan_id, items=raw_items, now_utc=now_utc)

    async def summarize_plan(
        self,
        *,
        session_id: str,
        llm: AsyncLLMClient,
    ) -> PlanSummaryResponse:
        plan = self.get_plan(session_id=session_id)
        if not plan.items or not getattr(llm, "_configured", False):
            return PlanSummaryResponse(summary_ar=None, referenced_item_ids=[], available=False)

        system_prompt, prompt_version = load_prompt("plan_summary")
        valid_ids = {it.id for it in plan.items}
        payload = {
            "as_of_date": plan.as_of_date,
            "conflicts": [c.message_ar for c in plan.conflicts],
            "items": [
                {
                    "item_id": it.id,
                    "priority_rank": it.priority_rank,
                    "title": it.title,
                    "eligible": it.eligible,
                    "match_percentage": it.match_percentage,
                    "deadline": it.deadline,
                    "days_remaining": it.days_remaining,
                    "urgency": it.urgency,
                    "progress_percentage": it.progress_percentage,
                }
                for it in plan.items[:10]
            ],
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            out = await llm.structured(
                messages,
                LLMPlanSummaryOutput,
                prompt_version=prompt_version,
                max_tokens=settings.PLANS_SUMMARY_MAX_TOKENS,
                temperature=0.1,
            )
            refs = [iid for iid in out.referenced_item_ids if iid in valid_ids]
            if not refs and out.referenced_item_ids:
                # Model cited unknown item IDs -> omit untrusted summary per invariant
                return PlanSummaryResponse(summary_ar=None, referenced_item_ids=[], available=False)
            return PlanSummaryResponse(
                summary_ar=out.summary_ar,
                referenced_item_ids=refs,
                prompt_version=prompt_version,
                available=True,
            )
        except LLMError:
            # Optional call: omit summary cleanly so deterministic plan stays completely usable
            return PlanSummaryResponse(summary_ar=None, referenced_item_ids=[], available=False)
