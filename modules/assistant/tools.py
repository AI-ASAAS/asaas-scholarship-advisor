"""Assistant tools wrapping the exact domain services and permissions (D8).

Read-only grant tools are available to all visitors; personalized profile,
matching, plan, and profile-update proposal tools require active consent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Set
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import asc, nulls_last, or_

from core.db import get_db
from core.models import Grant, GrantStatus
from core.repository import get_grant_by_id
from modules.auth.schemas import StudentPrincipal
from modules.matching.gpa import normalize_student_gpa
from modules.matching.nationalities import normalize_country_code
from modules.matching.service import compute_matches_from_db
from modules.students.schemas import DegreeLiteral, FundingNeedLiteral, GpaScaleLiteral, StudentLanguageItem
from modules.students.service import StudentService, scrub_pii_notes


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchGrantsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=60)
    degree: Optional[DegreeLiteral] = None
    field: Optional[str] = Field(default=None, max_length=80)
    limit: int = Field(default=5, ge=1, le=10)


class GetGrantArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: Optional[int] = Field(default=None, ge=1)
    title_query: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _require_selector(self) -> "GetGrantArgs":
        if self.grant_id is None and not (self.title_query and self.title_query.strip()):
            raise ValueError("Provide either grant_id or title_query.")
        return self


class MatchGrantsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=5, ge=1, le=10)


class CompareGrantsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_ids: List[int] = Field(..., min_length=2, max_length=3)


class ProposeProfileUpdateArgs(BaseModel):
    """Strict proposal schema for profile updates (never persists directly)."""

    model_config = ConfigDict(extra="forbid")

    nationality: Optional[str] = Field(default=None, max_length=60)
    country_of_residence: Optional[str] = Field(default=None, max_length=60)
    current_degree: Optional[DegreeLiteral] = None
    expected_graduation_year: Optional[int] = Field(default=None, ge=1990, le=2040)
    target_degree: Optional[DegreeLiteral] = None
    major: Optional[str] = Field(default=None, max_length=160)
    gpa_raw: Optional[str] = Field(default=None, max_length=32)
    gpa_scale: Optional[GpaScaleLiteral] = None
    add_language: Optional[StudentLanguageItem] = None
    target_countries: Optional[List[str]] = Field(default=None, max_length=20)
    target_fields: Optional[List[str]] = Field(default=None, max_length=20)
    funding_need: Optional[FundingNeedLiteral] = None
    work_experience_years: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    age_years: Optional[int] = Field(default=None, ge=14, le=80)
    experience_notes: Optional[List[str]] = Field(default=None, max_length=10)

    @field_validator("nationality", "country_of_residence")
    @classmethod
    def _check_country(cls, val: Optional[str]) -> Optional[str]:
        if val is None or not val.strip():
            return None
        code = normalize_country_code(val)
        if not code:
            raise ValueError("Invalid country code or name.")
        return code

    @model_validator(mode="after")
    def _check_non_empty_and_gpa(self) -> "ProposeProfileUpdateArgs":
        if self.gpa_raw is not None or self.gpa_scale is not None:
            normalize_student_gpa(self.gpa_raw, self.gpa_scale)
        provided = self.model_dump(exclude_none=True)
        if not provided:
            raise ValueError("At least one profile field update must be specified.")
        return self


@dataclass
class AssistantTool:
    name: str
    description: str
    parameters: type[BaseModel]
    run: Callable[[StudentPrincipal, Any], Awaitable[Dict[str, Any]]]
    writes: bool = False
    requires_consent: bool = False

    def spec(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters.model_json_schema(),
            },
        }


def _trim_grant_summary(g: Grant) -> Dict[str, Any]:
    return {
        "id": g.id,
        "title": g.title,
        "official_url": g.official_url,
        "deadline": g.deadline.isoformat() if g.deadline else None,
        "host_country": g.host_country,
        "allowed_degrees": g.allowed_degrees,
        "funding_type": g.funding_type,
        "accepts_yemeni": g.accepts_yemeni.value if hasattr(g.accepts_yemeni, "value") else g.accepts_yemeni,
        "featured_rank": g.featured_rank,
    }


def _trim_grant_detail(g: Grant) -> Dict[str, Any]:
    return {
        "id": g.id,
        "title": g.title,
        "official_url": g.official_url,
        "provider_name": g.provider_name,
        "host_country": g.host_country,
        "deadline": g.deadline.isoformat() if g.deadline else None,
        "funding_type": g.funding_type,
        "funding": g.funding,
        "allowed_degrees": g.allowed_degrees,
        "min_gpa_value": g.min_gpa_value,
        "min_gpa_scale": g.min_gpa_scale,
        "language_requirements": g.language_requirements,
        "min_work_years": g.min_work_years,
        "max_age": g.max_age,
        "nationality_rule": g.nationality_rule,
        "accepts_yemeni": g.accepts_yemeni.value if hasattr(g.accepts_yemeni, "value") else g.accepts_yemeni,
        "eligibility": g.eligibility,
        "fields_of_study": g.fields_of_study,
        "required_documents": g.required_documents,
        "how_to_apply": g.how_to_apply,
        "evidence": g.evidence or {},
    }


async def _run_search_grants(_principal: StudentPrincipal, args: SearchGrantsArgs) -> Dict[str, Any]:
    today = date.today()
    with get_db() as db:
        rows = (
            db.query(Grant)
            .filter(Grant.status == GrantStatus.PUBLISHED)
            .filter(or_(Grant.deadline.is_(None), Grant.deadline >= today))
            .order_by(asc(Grant.featured_rank), nulls_last(asc(Grant.deadline)))
            .all()
        )

    country_norm = normalize_country_code(args.country) if args.country else None
    q_low = (args.query or "").strip().lower()
    field_low = (args.field or "").strip().lower()

    matched: List[Dict[str, Any]] = []
    for g in rows:
        if country_norm and (g.host_country or "").upper() != country_norm:
            continue
        if args.degree and g.allowed_degrees and args.degree not in g.allowed_degrees:
            continue
        if field_low:
            fields_blob = " ".join(g.fields_of_study or []).lower()
            if field_low not in fields_blob and "all academic" not in fields_blob:
                continue
        if q_low:
            haystack = " ".join(
                [
                    g.title or "",
                    g.description or "",
                    g.provider_name or "",
                    g.host_country or "",
                    " ".join(g.fields_of_study or []),
                ]
            ).lower()
            if q_low not in haystack:
                continue
        matched.append(_trim_grant_summary(g))
        if len(matched) >= args.limit:
            break

    return {
        "count": len(matched),
        "grants": matched,
        "note": "No matching published grants found in platform catalog; suggest Deep Search." if not matched else None,
    }


async def _run_get_grant(_principal: StudentPrincipal, args: GetGrantArgs) -> Dict[str, Any]:
    with get_db() as db:
        grant: Optional[Grant] = None
        if args.grant_id is not None:
            candidate = get_grant_by_id(db, args.grant_id)
            if candidate is not None and candidate.status == GrantStatus.PUBLISHED:
                grant = candidate
        elif args.title_query:
            q = args.title_query.strip().lower()
            published = db.query(Grant).filter(Grant.status == GrantStatus.PUBLISHED).all()
            for candidate in published:
                if q in (candidate.title or "").lower() or q in (candidate.official_url or "").lower():
                    grant = candidate
                    break

        if grant is None:
            return {
                "found": False,
                "message": "Scholarship not found in verified platform catalog. Suggest using Deep Search.",
            }
        return {"found": True, "grant": _trim_grant_detail(grant)}


async def _run_get_my_profile(principal: StudentPrincipal, _args: NoArgs) -> Dict[str, Any]:
    if not principal.session_id:
        return {"profile_exists": False, "message": "Student has not saved a profile yet."}
    prof = StudentService().get_profile(principal.session_id)
    if prof is None:
        return {"profile_exists": False, "message": "Student has not saved a profile yet."}
    # Exclude consent metadata/timestamps unnecessary for academic advice
    return {
        "profile_exists": True,
        "profile": {
            "nationality": prof.nationality,
            "country_of_residence": prof.country_of_residence,
            "current_degree": prof.current_degree,
            "expected_graduation_year": prof.expected_graduation_year,
            "target_degree": prof.target_degree,
            "major": prof.major,
            "gpa_raw": prof.gpa_raw,
            "gpa_scale": prof.gpa_scale,
            "gpa_normalized_4": prof.gpa_normalized_4,
            "languages": [l.model_dump() for l in prof.languages],
            "target_countries": prof.target_countries,
            "target_fields": prof.target_fields,
            "funding_need": prof.funding_need,
            "work_experience_years": prof.work_experience_years,
            "age_years": prof.age_years,
        },
    }


async def _run_match_grants(principal: StudentPrincipal, args: MatchGrantsArgs) -> Dict[str, Any]:
    if not principal.session_id:
        return {"profile_exists": False, "message": "Ask the student to save a profile first."}
    prof = StudentService().get_profile(principal.session_id)
    if prof is None:
        return {"profile_exists": False, "message": "No profile saved yet; ask the student to complete /profile."}

    matches = compute_matches_from_db(prof.model_dump())
    top_eligible = [
        {
            "grant_id": m.grant_id,
            "title": m.title,
            "official_url": m.official_url,
            "deadline": m.deadline,
            "match_percentage": m.match_percentage,
            "coverage_percentage": m.coverage_percentage,
            "missing_info_hints": m.missing_info_hints[:3],
            "criteria": [
                {
                    "key": c.key,
                    "status": c.status,
                    "grant_value": c.grant_value,
                    "student_value": c.student_value,
                }
                for c in m.criteria
                if c.status != "not_applicable"
            ],
        }
        for m in matches.eligible_grants[: args.limit]
    ]
    top_ineligible = [
        {
            "grant_id": m.grant_id,
            "title": m.title,
            "official_url": m.official_url,
            "reasons": [d.reason_ar for d in m.disqualifiers],
        }
        for m in matches.ineligible_grants[:3]
    ]
    return {
        "profile_exists": True,
        "disclaimer": matches.disclaimer_ar,
        "eligible_count": len(matches.eligible_grants),
        "ineligible_count": len(matches.ineligible_grants),
        "eligible_grants": top_eligible,
        "ineligible_sample": top_ineligible,
    }


async def _run_get_my_plan(principal: StudentPrincipal, _args: NoArgs) -> Dict[str, Any]:
    if not principal.session_id:
        return {"available": True, "has_plan": False, "message": "No active student session yet."}
    from modules.plans.service import PlansService

    try:
        plan = PlansService().get_plan(session_id=principal.session_id)
    except ValueError as exc:
        if str(exc) == "PROFILE_NOT_FOUND":
            return {"available": True, "has_plan": False, "message": "Student profile is not saved yet; ask them to complete /profile first."}
        raise

    if not plan.items:
        return {
            "available": True,
            "has_plan": False,
            "total_grants": 0,
            "message": "The student's personal application plan is empty. Suggest adding grants from /matches.",
        }

    return {
        "available": True,
        "has_plan": True,
        "timezone": plan.timezone,
        "as_of_date": plan.as_of_date,
        "total_grants": plan.total_grants,
        "overall_progress_percentage": plan.overall_progress_percentage,
        "conflicts": [c.message_ar for c in plan.conflicts],
        "items": [
            {
                "priority_rank": it.priority_rank,
                "grant_id": it.grant_id,
                "title": it.title,
                "official_url": it.official_url,
                "eligible": it.eligible,
                "match_percentage": it.match_percentage,
                "deadline": it.deadline,
                "days_remaining": it.days_remaining,
                "urgency": it.urgency,
                "progress_percentage": it.progress_percentage,
                "todo_count": sum(1 for c in it.checklist if c.status != "done" and c.category != "missing_official"),
                "upcoming_milestones": [
                    {"due_date": m.due_date, "label_ar": m.label_ar, "status": m.status}
                    for m in it.milestones
                    if m.status in {"due_today", "due_soon", "upcoming"}
                ][:3],
            }
            for it in plan.items
        ],
    }


async def _run_compare_grants(_principal: StudentPrincipal, args: CompareGrantsArgs) -> Dict[str, Any]:
    with get_db() as db:
        items: List[Dict[str, Any]] = []
        for gid in args.grant_ids:
            g = get_grant_by_id(db, gid)
            if g is not None and g.status == GrantStatus.PUBLISHED:
                items.append(
                    {
                        "id": g.id,
                        "title": g.title,
                        "official_url": g.official_url,
                        "host_country": g.host_country,
                        "deadline": g.deadline.isoformat() if g.deadline else None,
                        "funding_type": g.funding_type,
                        "allowed_degrees": g.allowed_degrees,
                        "min_gpa_value": g.min_gpa_value,
                        "min_gpa_scale": g.min_gpa_scale,
                        "language_requirements": g.language_requirements,
                        "nationality_rule": g.nationality_rule,
                        "min_work_years": g.min_work_years,
                        "max_age": g.max_age,
                    }
                )
    return {
        "compared_count": len(items),
        "grants": items,
    }


async def _run_propose_profile_update(
    principal: StudentPrincipal,
    args: ProposeProfileUpdateArgs,
) -> Dict[str, Any]:
    raw_updates = args.model_dump(exclude_none=True)
    if "experience_notes" in raw_updates:
        raw_updates["experience_notes"] = scrub_pii_notes(raw_updates["experience_notes"])

    labels_ar = {
        "nationality": "الجنسية",
        "country_of_residence": "بلد الإقامة",
        "current_degree": "الدرجة الحالية",
        "expected_graduation_year": "سنة التخرج",
        "target_degree": "الدرجة المستهدفة",
        "major": "التخصص",
        "gpa_raw": "المعدل",
        "gpa_scale": "مقياس المعدل",
        "add_language": "إضافة لغة",
        "target_countries": "الدول المستهدفة",
        "target_fields": "المجالات المستهدفة",
        "funding_need": "تفضيل التمويل",
        "work_experience_years": "سنوات الخبرة",
        "age_years": "العمر",
        "experience_notes": "الإنجازات",
    }
    def _fmt_val(key: str, val: Any) -> str:
        if key == "add_language" and isinstance(val, dict):
            lang_name = val.get("language", "")
            test = val.get("test_name")
            score = val.get("score")
            cefr = val.get("self_assessed_cefr")
            detail = f"{test} ({score})" if test and score is not None else (cefr or "")
            return f"{lang_name} - {detail}".strip(" -")
        if isinstance(val, list):
            return ", ".join(str(x) for x in val)
        return str(val)

    summary_parts = [f"{labels_ar.get(k, k)}: {_fmt_val(k, v)}" for k, v in raw_updates.items()]
    return {
        "updates": raw_updates,
        "summary_ar": "، ".join(summary_parts),
        "summary_en": ", ".join(f"{k}: {_fmt_val(k, v)}" for k, v in raw_updates.items()),
    }


ASSISTANT_TOOLS: List[AssistantTool] = [
    AssistantTool(
        name="search_grants",
        description="Search published non-expired scholarships by text query, host country (ISO-2), degree level, or study field.",
        parameters=SearchGrantsArgs,
        run=_run_search_grants,
        writes=False,
        requires_consent=False,
    ),
    AssistantTool(
        name="get_grant",
        description="Get full verified details, deadline, documents, application instructions, and verbatim evidence for a published scholarship.",
        parameters=GetGrantArgs,
        run=_run_get_grant,
        writes=False,
        requires_consent=False,
    ),
    AssistantTool(
        name="compare_grants",
        description="Compare 2 to 3 published scholarships side-by-side by grant IDs.",
        parameters=CompareGrantsArgs,
        run=_run_compare_grants,
        writes=False,
        requires_consent=False,
    ),
    AssistantTool(
        name="get_my_profile",
        description="Read the current student's anonymized academic profile.",
        parameters=NoArgs,
        run=_run_get_my_profile,
        writes=False,
        requires_consent=True,
    ),
    AssistantTool(
        name="match_grants",
        description="Compute deterministic match percentages, coverage scores, and disqualifiers for the current student.",
        parameters=MatchGrantsArgs,
        run=_run_match_grants,
        writes=False,
        requires_consent=True,
    ),
    AssistantTool(
        name="get_my_plan",
        description="Read the student's personalized application plan, priority order, deadlines, checklist progress, and timeline conflicts.",
        parameters=NoArgs,
        run=_run_get_my_plan,
        writes=False,
        requires_consent=True,
    ),
    AssistantTool(
        name="propose_profile_update",
        description="Prepare a profile update proposal card for the student to review and confirm; NEVER saves directly.",
        parameters=ProposeProfileUpdateArgs,
        run=_run_propose_profile_update,
        writes=True,
        requires_consent=True,
    ),
]


def allowed_tools_for(principal: StudentPrincipal) -> Dict[str, AssistantTool]:
    """Filter offered tools strictly on the server based on session consent."""
    can_use_personal = bool(principal.authenticated and principal.session_id and principal.has_consent)
    return {
        tool.name: tool
        for tool in ASSISTANT_TOOLS
        if (not tool.requires_consent) or can_use_personal
    }
