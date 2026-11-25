"""Service layer for profile strengthening (Capability 6) and document help (Capability 7)."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional, Tuple
from sqlalchemy import or_

from core.config import settings
from core.db import get_db
from core.models import Grant, GrantStatus
from core.repository import get_grant_by_id
from modules.documents.ledger import build_facts_ledger, verify_draft_against_ledger
from modules.documents.repository import DocumentsRepository
from modules.documents.schemas import (
    DocumentDraftUpdateRequest,
    DocumentGenerateRequest,
    DocumentGenerateResponse,
    DocumentSaveRequest,
    FlaggedClaim,
    LLMDocumentDraftOutput,
    LLMStrengtheningResponse,
    SavedDocumentDraftResponse,
    StrengtheningActionItem,
    StrengtheningGap,
    StrengtheningRequest,
    StrengtheningResponse,
)
from modules.llm.client import AsyncLLMClient, LLMError
from modules.llm.prompts import load_prompt
from modules.matching.analysis import build_deterministic_findings
from modules.matching.service import compute_matches_for_student
from modules.students.service import StudentService, scrub_pii_notes

logger = logging.getLogger(__name__)

_DOCUMENT_RESPONSIBILITY_AR = (
    "ملاحظة مسؤولية: أنت وحدك المسؤول عن دقة ومراجعة جميع المحتويات والأرقام قبل التقديم الرسمي. "
    "لا يضمن أي مستند القبول في المنحة."
)
_DOCUMENT_RESPONSIBILITY_EN = (
    "Responsibility note: You are solely responsible for reviewing and verifying all facts, grades, "
    "and claims before official submission. No document guarantees scholarship admission."
)
_STRENGTHENING_DISCLAIMER_AR = (
    "هذه التوصيات مبنية على شروط المنح المنشورة وملفك الحالي. التقديرات الزمنية للتحضير افتراضية قابلة للتعديل ولا تضمن القبول."
)
_STRENGTHENING_DISCLAIMER_EN = (
    "Recommendations are derived strictly from published grant criteria and your current profile. "
    "Preparation timeframes are labeled assumptions and do not guarantee admission."
)


def _grant_to_eval_dict(g: Grant) -> Dict[str, Any]:
    return {
        "id": g.id,
        "title": g.title,
        "official_url": g.official_url,
        "description": g.description,
        "eligibility": g.eligibility,
        "criteria": g.criteria,
        "fields_of_study": g.fields_of_study,
        "funding": g.funding,
        "required_documents": g.required_documents,
        "deadline": g.deadline,
        "how_to_apply": g.how_to_apply,
        "accepts_yemeni": g.accepts_yemeni.value if hasattr(g.accepts_yemeni, "value") else g.accepts_yemeni,
        "provider_name": g.provider_name,
        "host_country": g.host_country,
        "allowed_degrees": g.allowed_degrees,
        "min_gpa_value": g.min_gpa_value,
        "min_gpa_scale": g.min_gpa_scale,
        "min_gpa_normalized_4": g.min_gpa_normalized_4,
        "language_requirements": g.language_requirements,
        "nationality_rule": g.nationality_rule,
        "min_work_years": g.min_work_years,
        "max_age": g.max_age,
        "funding_type": g.funding_type,
        "status": g.status.value if hasattr(g.status, "value") else g.status,
        "featured_rank": g.featured_rank,
        "evidence": g.evidence or {},
    }


def _strip_pii_from_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "nationality": profile.get("nationality"),
        "country_of_residence": profile.get("country_of_residence"),
        "current_degree": profile.get("current_degree"),
        "expected_graduation_year": profile.get("expected_graduation_year"),
        "target_degree": profile.get("target_degree"),
        "major": profile.get("major"),
        "gpa_raw": profile.get("gpa_raw"),
        "gpa_scale": profile.get("gpa_scale"),
        "gpa_normalized_4": profile.get("gpa_normalized_4"),
        "languages": profile.get("languages") or [],
        "target_countries": profile.get("target_countries") or [],
        "target_fields": profile.get("target_fields") or [],
        "funding_need": profile.get("funding_need"),
        "work_experience_years": profile.get("work_experience_years"),
        "experience_notes": scrub_pii_notes(list(profile.get("experience_notes") or [])),
        "age_years": profile.get("age_years"),
        "publications_count": profile.get("publications_count", 0),
    }


def compute_deterministic_gaps(
    profile: Mapping[str, Any],
    grants: List[Dict[str, Any]],
    *,
    reference_date: Optional[date] = None,
    assumed_test_weeks: Optional[int] = None,
) -> List[StrengtheningGap]:
    """Build concrete strengthening gaps from Phase 3 matching findings & grant criteria."""
    ref = reference_date or date.today()
    test_weeks = assumed_test_weeks if assumed_test_weeks is not None else settings.DOCUMENTS_ASSUMED_LANGUAGE_TEST_WEEKS

    matches = compute_matches_for_student(profile, grants, reference_date=ref)
    grants_by_id = {g["id"]: g for g in grants}
    findings = build_deterministic_findings(profile, matches, grants_by_id=grants_by_id)

    gaps: List[StrengtheningGap] = []
    idx = 1

    # Inspect target pool (matched grants or evaluated grants)
    pool = matches.eligible_grants[:5] if matches.eligible_grants else matches.ineligible_grants[:5]
    has_language_score = any(
        isinstance(item, Mapping) and (item.get("score") is not None or item.get("self_assessed_cefr"))
        for item in (profile.get("languages") or [])
    )

    # 1. Language gaps & too-close deadlines for taking a language test
    lang_grants: List[str] = []
    lang_quotes: List[str] = []
    close_deadline_grants: List[str] = []
    min_close_days: Optional[int] = None

    for m in pool:
        g = grants_by_id.get(m.grant_id, {})
        lang_crit = [c for c in m.criteria if c.key == "language" and c.status in {"unknown", "not_met"}]
        if lang_crit or (g.get("language_requirements") and not has_language_score):
            lang_grants.append(m.title)
            ev_q = (g.get("evidence") or {}).get("language_requirements")
            if ev_q:
                lang_quotes.append(f"{m.title}: \"{ev_q}\"")
            elif lang_crit and lang_crit[0].grant_value:
                lang_quotes.append(f"{m.title}: {lang_crit[0].grant_value}")
            dl = g.get("deadline")
            if isinstance(dl, date):
                days_left = (dl - ref).days
                if 0 <= days_left < test_weeks * 7:
                    close_deadline_grants.append(f"{m.title} ({dl.isoformat()})")
                    if min_close_days is None or days_left < min_close_days:
                        min_close_days = days_left

    if lang_grants:
        ev_text = " | ".join(lang_quotes[:3]) or f"مطلوب في {len(lang_grants)} منحة"
        gaps.append(
            StrengtheningGap(
                gap_id=f"G{idx}",
                gap_type="language",
                severity="high",
                title_ar="اختبار وإثبات كفاءة اللغة",
                title_en="Language proficiency test proof",
                evidence_ar=f"شروط المنح: {ev_text}",
                evidence_en=f"Grant criteria: {ev_text}",
                related_grants=lang_grants[:4],
            )
        )
        idx += 1

    if close_deadline_grants and not has_language_score:
        gaps.append(
            StrengtheningGap(
                gap_id=f"G{idx}",
                gap_type="deadline_proximity",
                severity="high",
                title_ar="ضيق الوقت قبل إغلاق التقديم لاختبار اللغة (تقدير افتراضي)",
                title_en="Tight deadline for language testing (assumed lead time)",
                evidence_ar=(
                    f"أقرب موعد إغلاق خلال {min_close_days} يوماً ({', '.join(close_deadline_grants[:3])}) "
                    f"مقارنة بنافذة تحضير افتراضية قدرها {test_weeks} أسابيع."
                ),
                evidence_en=(
                    f"Closest deadline in {min_close_days} days ({', '.join(close_deadline_grants[:3])}) "
                    f"vs assumed {test_weeks}-week prep window."
                ),
                related_grants=close_deadline_grants[:4],
                is_assumption=True,
                assumption_note_ar=f"تقدير افتراضي قابل للتعديل: نافذة التحضير وحجز الاختبار {test_weeks} أسابيع.",
                assumption_note_en=f"Configurable assumption: {test_weeks}-week language test prep window.",
            )
        )
        idx += 1

    # 2. GPA below stated minimums
    gpa_failed_grants: List[str] = []
    gpa_quotes: List[str] = []
    for m in matches.ineligible_grants + matches.eligible_grants:
        g = grants_by_id.get(m.grant_id, {})
        failed_gpa = any(d.gate == "gpa" for d in m.disqualifiers) or any(
            c.key == "gpa" and c.status == "not_met" for c in m.criteria
        )
        if failed_gpa:
            gpa_failed_grants.append(m.title)
            ev_q = (g.get("evidence") or {}).get("min_gpa")
            if ev_q:
                gpa_quotes.append(f"{m.title}: \"{ev_q}\"")
            elif g.get("min_gpa_value"):
                gpa_quotes.append(f"{m.title}: {g.get('min_gpa_value')}/{g.get('min_gpa_scale')}")

    if gpa_failed_grants:
        ev_text = " | ".join(gpa_quotes[:3]) or ", ".join(gpa_failed_grants[:3])
        gaps.append(
            StrengtheningGap(
                gap_id=f"G{idx}",
                gap_type="gpa",
                severity="medium",
                title_ar="المعدل التراكمي أقل من الحد المذكور في بعض المنح",
                title_en="GPA below stated minimum on target grants",
                evidence_ar=f"شروط المعدل المعلنة: {ev_text}",
                evidence_en=f"Stated GPA minimums: {ev_text}",
                related_grants=gpa_failed_grants[:4],
            )
        )
        idx += 1

    # 3. Missing commonly required documents from Phase 3 findings
    for f in findings:
        if f.kind == "documents":
            gaps.append(
                StrengtheningGap(
                    gap_id=f"G{idx}",
                    gap_type="documents",
                    severity="medium",
                    title_ar="تجهيز الوثائق المشتركة المطلوبة للتقديم",
                    title_en="Commonly required application documents",
                    evidence_ar=f.summary_ar,
                    evidence_en=f.summary_en,
                    related_grants=list(f.related_grants[:4]),
                )
            )
            idx += 1
        elif f.kind == "gap" and not any(g.gap_type == "language" for g in gaps) and "لغة" in f.summary_ar:
            gaps.append(
                StrengtheningGap(
                    gap_id=f"G{idx}",
                    gap_type="other",
                    severity="medium",
                    title_ar="نقص بيانات غير مكتملة في الملف",
                    title_en="Missing profile criteria",
                    evidence_ar=f.summary_ar,
                    evidence_en=f.summary_en,
                    related_grants=list(f.related_grants[:4]),
                )
            )
            idx += 1

    return gaps


_DOC_LABELS: Dict[str, Tuple[str, str]] = {
    "cv": ("السيرة الذاتية (CV)", "CV"),
    "motivation_letter": ("رسالة الدافع", "Motivation Letter"),
    "recommendation_support": ("نقاط دعم التوصية", "Recommendation Support"),
    "certificates": ("الشهادات والمؤهلات", "Certificates & Qualifications"),
}


def _deterministic_strengthening_fallback(gaps: List[StrengtheningGap]) -> Tuple[str, List[StrengtheningActionItem]]:
    actions: List[StrengtheningActionItem] = []
    for g in gaps:
        if g.gap_id.startswith("G_DOC_"):
            actions.append(
                StrengtheningActionItem(
                    gap_id=g.gap_id,
                    what_ar=g.title_ar,
                    why_ar=g.evidence_ar,
                    next_step_ar="راجع هذا المستند في قسم التحسين والمراجعة أدناه لمواءمته مع متطلبات المنح الموثّقة دون اختلاق أي بيانات.",
                    is_assumption=False,
                )
            )
        elif g.gap_type == "language":
            actions.append(
                StrengtheningActionItem(
                    gap_id=g.gap_id,
                    what_ar="توثيق شهادة لغة معترف بها (مثل IELTS أو TOEFL) أو تحديث مستواك الفعلي",
                    why_ar=g.evidence_ar,
                    next_step_ar="راجع شرط اللغة في البوابة الرسمية لكل منحة مستهدفة وسجّل درجتك فور توفرها في ملفك.",
                    is_assumption=g.is_assumption,
                )
            )
        elif g.gap_type == "deadline_proximity":
            actions.append(
                StrengtheningActionItem(
                    gap_id=g.gap_id,
                    what_ar="إعطاء الأولوية للمنح ذات الموعد الأقرب أو المنح التي تقبل إثبات الدراسة بالإنجليزية",
                    why_ar=g.evidence_ar,
                    next_step_ar="تحقق من مواعيد نتائج الاختبار الرسمية مقارنة بتاريخ الإغلاق، وركّز على المنح الملائمة زمنياً.",
                    is_assumption=True,
                )
            )
        elif g.gap_type == "gpa":
            actions.append(
                StrengtheningActionItem(
                    gap_id=g.gap_id,
                    what_ar="التعويض عن فجوة المعدل التراكمي بالتركيز على الخبرة البحثية والمنح المناسبة لدرجتك",
                    why_ar=g.evidence_ar,
                    next_step_ar="وجّه طلباتك أولاً للمنح التي يتوافق معدلك الموحّد مع حدّها الأدنى، وأبرز خبرتك ومشاريعك الموثقة.",
                    is_assumption=g.is_assumption,
                )
            )
        else:
            actions.append(
                StrengtheningActionItem(
                    gap_id=g.gap_id,
                    what_ar=g.title_ar,
                    why_ar=g.evidence_ar,
                    next_step_ar="ابدأ بتجهيز مسودات السيرة الذاتية وخطاب الدافع وطلبات التوصية في قسم مستنداتي.",
                    is_assumption=g.is_assumption,
                )
            )
    summary = (
        f"تم تحديد {len(gaps)} فجوات واضحة بناءً على ملفك وشروط المنح المنشورة (توصيات أولية حتمية)."
        if gaps
        else "ملفك يغطي المتطلبات الأساسية الظاهرة للمنح المقترحة؛ راجع الوثائق المطلوبة لكل منحة قبل الإغلاق."
    )
    return summary, actions


class DocumentsService:
    """Orchestrates Capability 6 strengthening and Capability 7 anti-fabrication drafting."""

    async def strengthen_profile(
        self,
        *,
        session_id: str,
        request: StrengtheningRequest,
        llm: AsyncLLMClient,
    ) -> StrengtheningResponse:
        profile = StudentService().get_profile(session_id)
        if profile is None:
            raise ValueError("PROFILE_NOT_FOUND")
        prof_dict = profile.model_dump()

        with get_db() as db:
            query = db.query(Grant).filter(Grant.status == GrantStatus.PUBLISHED)
            if request.grant_ids:
                query = query.filter(Grant.id.in_(request.grant_ids))
            else:
                today = date.today()
                query = query.filter(or_(Grant.deadline.is_(None), Grant.deadline >= today))
            grants = [_grant_to_eval_dict(g) for g in query.all()]

        gaps = compute_deterministic_gaps(prof_dict, grants)

        submitted_docs_payload: List[Dict[str, Any]] = []
        seen_doc_types = set()
        for doc in request.documents or []:
            if doc.doc_type in seen_doc_types:
                continue
            seen_doc_types.add(doc.doc_type)
            scrubbed_list = scrub_pii_notes([doc.content])
            clean_doc_text = (scrubbed_list[0] if scrubbed_list else "").strip()
            if len(clean_doc_text) < 10:
                continue
            label_ar, label_en = _DOC_LABELS.get(doc.doc_type, (doc.doc_type, doc.doc_type))
            safe_name = os.path.basename(doc.filename.strip()) if doc.filename else None
            gap_id = f"G_DOC_{doc.doc_type.upper()}"
            file_note_ar = f" ({safe_name})" if safe_name else ""
            file_note_en = f" ({safe_name})" if safe_name else ""
            gaps.append(
                StrengtheningGap(
                    gap_id=gap_id,
                    gap_type="documents",
                    severity="medium",
                    title_ar=f"مراجعة وتقوية {label_ar}",
                    title_en=f"Review and strengthen {label_en}",
                    evidence_ar=(
                        f"تم إرفاق نص {label_ar}{file_note_ar} ({len(clean_doc_text)} حرفاً) "
                        f"لمراجعته ومواءمته مع شروط المنح المستهدفة."
                    ),
                    evidence_en=(
                        f"Submitted {label_en}{file_note_en} ({len(clean_doc_text)} chars) "
                        f"for alignment review against target grant requirements."
                    ),
                    related_grants=[g["title"] for g in grants[:3]],
                )
            )
            submitted_docs_payload.append(
                {
                    "gap_id": gap_id,
                    "doc_type": doc.doc_type,
                    "filename": safe_name,
                    "content": f'<STUDENT_DOCUMENT type="{doc.doc_type}">\n{clean_doc_text[:2500]}\n</STUDENT_DOCUMENT>',
                }
            )

        if not gaps:
            summary, actions = _deterministic_strengthening_fallback(gaps)
            return StrengtheningResponse(
                gaps=[],
                summary_ar=summary,
                actions=actions,
                prompt_version=None,
                used_fallback=True,
                disclaimer_ar=_STRENGTHENING_DISCLAIMER_AR,
                disclaimer_en=_STRENGTHENING_DISCLAIMER_EN,
            )

        if not getattr(llm, "_configured", False):
            summary, actions = _deterministic_strengthening_fallback(gaps)
            return StrengtheningResponse(
                gaps=gaps,
                summary_ar=summary,
                actions=actions,
                prompt_version=None,
                used_fallback=True,
                disclaimer_ar=_STRENGTHENING_DISCLAIMER_AR,
                disclaimer_en=_STRENGTHENING_DISCLAIMER_EN,
            )

        system_prompt, prompt_version = load_prompt("strengthening")
        payload: Dict[str, Any] = {
            "student_profile": _strip_pii_from_profile(prof_dict),
            "gaps": [g.model_dump() for g in gaps],
        }
        if submitted_docs_payload:
            payload["submitted_documents"] = submitted_docs_payload
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            llm_out = await llm.structured(
                messages,
                LLMStrengtheningResponse,
                prompt_version=prompt_version,
                max_tokens=settings.DOCUMENTS_MAX_TOKENS,
                temperature=0.2,
            )
            gaps_by_id = {g.gap_id: g for g in gaps}
            verified_actions = [
                StrengtheningActionItem(
                    gap_id=item.gap_id,
                    what_ar=item.what_ar,
                    why_ar=item.why_ar,
                    next_step_ar=item.next_step_ar,
                    is_assumption=gaps_by_id[item.gap_id].is_assumption,
                )
                for item in llm_out.actions
                if item.gap_id in gaps_by_id
            ]
            if not verified_actions:
                _, verified_actions = _deterministic_strengthening_fallback(gaps)
            return StrengtheningResponse(
                gaps=gaps,
                summary_ar=llm_out.summary_ar,
                actions=verified_actions,
                prompt_version=prompt_version,
                used_fallback=False,
                disclaimer_ar=_STRENGTHENING_DISCLAIMER_AR,
                disclaimer_en=_STRENGTHENING_DISCLAIMER_EN,
            )
        except LLMError:
            raise

    async def generate_draft(
        self,
        *,
        session_id: str,
        request: DocumentGenerateRequest,
        llm: AsyncLLMClient,
    ) -> DocumentGenerateResponse:
        profile = StudentService().get_profile(session_id)
        if profile is None:
            raise ValueError("PROFILE_NOT_FOUND")
        prof_dict = _strip_pii_from_profile(profile.model_dump())

        grant_dict: Optional[Dict[str, Any]] = None
        if request.grant_id is not None:
            with get_db() as db:
                g = get_grant_by_id(db, request.grant_id)
                if g is None or g.status != GrantStatus.PUBLISHED:
                    raise LookupError("GRANT_NOT_FOUND")
                grant_dict = _grant_to_eval_dict(g)

        scrubbed_source_list = scrub_pii_notes([request.source_text])
        clean_source = scrubbed_source_list[0] if scrubbed_source_list else ""

        ledger, conflicts, missing_requests = build_facts_ledger(
            profile=prof_dict,
            source_text=clean_source,
            grant=grant_dict,
        )

        system_prompt, prompt_version = load_prompt("documents")
        model_input = {
            "doc_type": request.doc_type,
            "target_language": request.language,
            "target_instructions": (scrub_pii_notes([request.target_instructions])[0] if request.target_instructions else None),
            "target_grant": (
                {
                    "title": grant_dict["title"],
                    "official_url": grant_dict["official_url"],
                    "deadline": grant_dict["deadline"].isoformat() if grant_dict.get("deadline") else None,
                    "criteria": grant_dict.get("criteria") or [],
                    "required_documents": grant_dict.get("required_documents") or [],
                    "how_to_apply": grant_dict.get("how_to_apply"),
                }
                if grant_dict
                else None
            ),
            "facts_ledger": [e.model_dump(exclude={"normalized_tokens"}) for e in ledger if e.category != "raw_text"],
            "missing_profile_fields": missing_requests,
            "STUDENT_TEXT": f"<STUDENT_TEXT>\n{clean_source}\n</STUDENT_TEXT>",
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(model_input, ensure_ascii=False)},
        ]
        llm_out = await llm.structured(
            messages,
            LLMDocumentDraftOutput,
            prompt_version=prompt_version,
            max_tokens=settings.DOCUMENTS_MAX_TOKENS,
            temperature=0.2,
        )

        flagged = verify_draft_against_ledger(
            draft_text=llm_out.draft_text,
            doc_type=request.doc_type,
            ledger=ledger,
            existing_conflicts=conflicts,
        )
        merged_missing = list(dict.fromkeys([*missing_requests, *llm_out.missing_info_requests]))

        return DocumentGenerateResponse(
            grant_id=grant_dict["id"] if grant_dict else None,
            grant_title=grant_dict["title"] if grant_dict else None,
            doc_type=request.doc_type,
            language=request.language,
            draft_text=llm_out.draft_text,
            sections=llm_out.sections,
            facts_ledger=ledger,
            claims=llm_out.claims,
            flagged_claims=flagged,
            conflicts=conflicts,
            missing_info_requests=merged_missing,
            prompt_version=prompt_version,
            responsibility_note_ar=_DOCUMENT_RESPONSIBILITY_AR,
            responsibility_note_en=_DOCUMENT_RESPONSIBILITY_EN,
        )

    def list_saved_drafts(self, session_id: str) -> List[SavedDocumentDraftResponse]:
        with get_db() as db:
            DocumentsRepository.purge_expired_drafts(db, settings.DOCUMENTS_RETENTION_DAYS)
            rows = DocumentsRepository.list_drafts(db, session_id)
            return [SavedDocumentDraftResponse(**r) for r in rows]

    def save_draft(self, session_id: str, payload: DocumentSaveRequest) -> SavedDocumentDraftResponse:
        # Re-verify before saving whenever ledger is supplied
        rechecked_flags = (
            verify_draft_against_ledger(
                draft_text=payload.draft_text,
                doc_type=payload.doc_type,
                ledger=payload.facts_ledger,
                existing_conflicts=[c for c in payload.flagged_claims if c.category == "conflict" or c.status != "needs_confirmation"],
            )
            if payload.facts_ledger
            else list(payload.flagged_claims)
        )
        # Preserve already accepted/removed statuses from user interaction
        prior_status = {c.id: c.status for c in payload.flagged_claims}
        final_flags: List[Dict[str, Any]] = []
        for fc in rechecked_flags:
            item = fc.model_dump()
            if fc.id in prior_status:
                item["status"] = prior_status[fc.id]
            final_flags.append(item)

        with get_db() as db:
            DocumentsRepository.purge_expired_drafts(db, settings.DOCUMENTS_RETENTION_DAYS)
            rec = DocumentsRepository.create_draft(
                db,
                session_id=session_id,
                grant_id=payload.grant_id,
                doc_type=payload.doc_type,
                language=payload.language,
                facts_ledger=[e.model_dump() for e in payload.facts_ledger],
                draft_text=payload.draft_text,
                flagged_claims=final_flags,
                prompt_version=payload.prompt_version,
            )
            return SavedDocumentDraftResponse(**rec)

    def update_saved_draft(
        self,
        session_id: str,
        draft_id: int,
        payload: DocumentDraftUpdateRequest,
    ) -> Optional[SavedDocumentDraftResponse]:
        with get_db() as db:
            existing = DocumentsRepository.get_draft(db, session_id, draft_id)
            if existing is None:
                return None
            rec = DocumentsRepository.update_draft(
                db,
                session_id=session_id,
                draft_id=draft_id,
                draft_text=payload.draft_text,
                flagged_claims=(
                    [c.model_dump() for c in payload.flagged_claims]
                    if payload.flagged_claims is not None
                    else None
                ),
            )
            return SavedDocumentDraftResponse(**rec) if rec else None

    def delete_saved_draft(self, session_id: str, draft_id: int) -> bool:
        with get_db() as db:
            return DocumentsRepository.delete_draft(db, session_id, draft_id)

    def get_draft_for_export(self, session_id: str, draft_id: int) -> Optional[Tuple[str, str]]:
        with get_db() as db:
            rec = DocumentsRepository.get_draft(db, session_id, draft_id)
            if rec is None:
                return None
            header = (
                f"ASAAS Scholarship Advisor - Document ({rec['doc_type']})\n"
                f"{'Target Grant: ' + rec['grant_title'] if rec.get('grant_title') else ''}\n"
                f"{_DOCUMENT_RESPONSIBILITY_EN}\n"
                + ("=" * 60)
                + "\n\n"
            )
            return f"asaas-document-{draft_id}.txt", header + rec["draft_text"]
