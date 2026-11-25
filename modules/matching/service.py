"""Deterministic matching engine (D5, D6).

All eligibility gates, per-criterion verdicts, weighted percentages,
coverage ratios, and missing-information hints are computed purely in
Python code from verified grant conditions and student profile values.
No LLM calls are ever executed here.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.db import get_db
from core.models import Grant, GrantStatus
from modules.matching.gpa import get_gpa_scales_config
from modules.matching.nationalities import evaluate_nationality
from modules.matching.schemas import (
    CriterionBreakdown,
    DisqualifierItem,
    GrantMatchResult,
    MatchesListResponse,
)

_WEIGHTS_PATH = Path(__file__).resolve().parent / "weights.json"

_CEFR_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


@lru_cache(maxsize=1)
def get_weights_config() -> Dict[str, Any]:
    return json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))


def _tokenize(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    return {t for t in re.findall(r"[a-z0-9\u0600-\u06ff]+", text.lower()) if len(t) > 2}


def _evaluate_field_match(
    grant_fields: Optional[List[str]],
    student_major: Optional[str],
    student_target_fields: List[str],
) -> Tuple[str, Optional[str], Optional[str], str, str]:
    if not grant_fields:
        return (
            "not_applicable",
            None,
            student_major or (", ".join(student_target_fields) if student_target_fields else None),
            "لا تشترط المنحة تخصصاً محدداً.",
            "Grant does not restrict eligible fields of study.",
        )

    lowered_list = [f.lower() for f in grant_fields]
    if any("all academic" in f or f.strip() == "all" for f in lowered_list):
        return (
            "met",
            ", ".join(grant_fields[:3]),
            student_major or (", ".join(student_target_fields) if student_target_fields else "All"),
            "تشمل المنحة جميع التخصصات الأكاديمية (عدا الاستثناءات المذكورة).",
            "Grant covers all academic fields.",
        )

    student_terms: List[str] = []
    if student_major:
        student_terms.append(student_major)
    student_terms.extend(student_target_fields)
    if not student_terms:
        return (
            "unknown",
            ", ".join(grant_fields[:4]),
            None,
            "أضف تخصصك أو مجالاتك المستهدفة لمطابقة تخصصات المنحة.",
            "Add your major or target fields to check field alignment.",
        )

    student_tokens = set()
    for term in student_terms:
        student_tokens |= _tokenize(term)

    grant_tokens = set()
    for gf in grant_fields:
        grant_tokens |= _tokenize(gf)

    # Check substring or meaningful token overlap
    direct_match = any(
        any(st.lower() in gf or gf in st.lower() for gf in lowered_list)
        for st in student_terms
    )
    overlap = student_tokens & grant_tokens
    if direct_match or len(overlap) > 0:
        return (
            "met",
            ", ".join(grant_fields[:4]),
            ", ".join(student_terms[:2]),
            "تخصصك يتقاطع مع المجالات المشمولة في المنحة.",
            "Your academic field aligns with grant fields of study.",
        )
    return (
        "not_met",
        ", ".join(grant_fields[:4]),
        ", ".join(student_terms[:2]),
        "التخصصات المعلنة في المنحة لا تطابق تخصصك المسجّل.",
        "Published grant fields do not match your stated field/interests.",
    )


def _evaluate_language(
    grant_langs: Optional[List[Dict[str, Any]]],
    student_langs: List[Dict[str, Any]],
) -> Tuple[str, Optional[str], Optional[str], str, str, Optional[str]]:
    """Evaluate structured language requirements cleanly.

    Returns: (status, grant_val, student_val, reason_ar, reason_en, missing_hint)
    """
    if not grant_langs:
        return (
            "not_applicable",
            None,
            None,
            "لم تنص المنحة على متطلب لغة رقمي.",
            "No explicit language requirement published.",
            None,
        )

    grant_desc = "; ".join(
        " ".join(
            str(p)
            for p in (
                req.get("language"),
                req.get("test"),
                req.get("min_score"),
                req.get("cefr"),
            )
            if p is not None
        )
        for req in grant_langs
    )

    if not student_langs:
        first_test = next((r.get("test") for r in grant_langs if r.get("test")), None)
        hint = (
            f"تشترط المنحة شهادة لغة ({first_test})؛ أضف درجتك اللغوية لحسم هذا الشرط."
            if first_test
            else "تشترط المنحة إثبات كفاءة لغوية؛ أضف مستواك أو شهادتك اللغوية."
        )
        return (
            "unknown",
            grant_desc,
            None,
            "لم تُضف شهادات أو مستويات لغة في ملفك بعد.",
            "No language score or level added to your profile yet.",
            hint,
        )

    # Check if student satisfies at least one required language entry (or all stated ones)
    all_met = True
    any_unknown = False
    student_summaries: List[str] = []

    for sl in student_langs:
        label = sl.get("language", "")
        if sl.get("test_name") and sl.get("score") is not None:
            student_summaries.append(f"{label} ({sl['test_name']} {sl['score']})")
        elif sl.get("self_assessed_cefr"):
            student_summaries.append(f"{label} (ذاتي {sl['self_assessed_cefr']})")
        else:
            student_summaries.append(f"{label} (تقييم ذاتي)")
    student_val_str = ", ".join(student_summaries)

    for req in grant_langs:
        req_lang = str(req.get("language") or "").strip().lower()
        req_test = str(req.get("test") or "").strip().upper() if req.get("test") else None
        req_score = req.get("min_score")
        req_cefr = str(req.get("cefr") or "").strip().upper() if req.get("cefr") else None

        matching_student = [
            sl for sl in student_langs if str(sl.get("language") or "").strip().lower() == req_lang
        ]
        if not matching_student:
            any_unknown = True
            all_met = False
            continue

        # Prefer official tests first
        official = [
            sl
            for sl in matching_student
            if not sl.get("is_self_assessed") and sl.get("test_name") and sl.get("score") is not None
        ]
        if req_test:
            by_test = [sl for sl in official if str(sl.get("test_name") or "").upper() == req_test]
            if by_test:
                best_score = max(float(sl["score"]) for sl in by_test)
                if req_score is not None:
                    if best_score < float(req_score):
                        return (
                            "not_met",
                            grant_desc,
                            student_val_str,
                            f"درجة {req_test} لديك ({best_score}) أقل من الحد المطلوب ({req_score}).",
                            f"Your {req_test} score ({best_score}) is below minimum ({req_score}).",
                            None,
                        )
                # Matches named test
                continue
            # Student didn't provide the named official test (maybe provided self-assessed)
            any_unknown = True
            all_met = False
            continue

        # No specific test named by grant (only language / CEFR)
        if official:
            continue
        if req_cefr and any(
            _CEFR_ORDER.get(str(sl.get("self_assessed_cefr") or "").upper(), 0)
            >= _CEFR_ORDER.get(req_cefr, 0)
            for sl in matching_student
        ):
            continue
        any_unknown = True
        all_met = False

    if all_met:
        return (
            "met",
            grant_desc,
            student_val_str,
            "مستوى اللغة أو الاختبار المسجّل يستوفي متطلب المنحة.",
            "Your stated language qualification meets the requirement.",
            None,
        )

    if any_unknown:
        req_names = ", ".join(r.get("test") or r.get("language", "") for r in grant_langs)
        return (
            "unknown",
            grant_desc,
            student_val_str,
            "تتطلب المنحة إثباتاً رسمياً أو اختباراً محدداً غير مكتمل في ملفك.",
            "Grant specifies a language test/proof not yet matched by an official score in your profile.",
            f"أضف نتيجة اختبار معتمد ({req_names}) لتقييم هذا الشرط بدقة.",
        )

    return (
        "unknown",
        grant_desc,
        student_val_str,
        "معلومات اللغة غير كافية للجزم.",
        "Insufficient language information.",
        "حدّث بيانات اللغة في ملفك الشخصي.",
    )


def evaluate_grant_for_student(
    grant: Mapping[str, Any],
    student: Mapping[str, Any],
    *,
    weights_cfg: Optional[Dict[str, Any]] = None,
    reference_date: Optional[date] = None,
) -> GrantMatchResult:
    """Deterministically evaluate a single grant against a student profile (D6)."""
    cfg = weights_cfg or get_weights_config()
    weights: Dict[str, int] = cfg["weights"]
    weights_version = str(cfg.get("version", "1.0"))
    today = reference_date or date.today()

    evidence: Dict[str, str] = dict(grant.get("evidence") or {})
    disqualifiers: List[DisqualifierItem] = []

    # 1. Hard Gate: Published status
    if str(grant.get("status") or "").lower() != "published":
        disqualifiers.append(
            DisqualifierItem(
                gate="status",
                reason_ar="المنحة ليست في حالة منشورة حالياً.",
                reason_en="Grant is not currently published.",
            )
        )

    # 2. Hard Gate: Deadline expired
    raw_deadline = grant.get("deadline")
    deadline_date: Optional[date] = None
    if isinstance(raw_deadline, date):
        deadline_date = raw_deadline
    elif isinstance(raw_deadline, str) and raw_deadline.strip():
        try:
            deadline_date = date.fromisoformat(raw_deadline.strip()[:10])
        except ValueError:
            deadline_date = None

    if deadline_date is not None and deadline_date < today:
        disqualifiers.append(
            DisqualifierItem(
                gate="deadline",
                reason_ar=f"انتهى الموعد النهائي للتقديم ({deadline_date.isoformat()}).",
                reason_en=f"Application deadline has passed ({deadline_date.isoformat()}).",
                evidence_quote=evidence.get("deadline"),
            )
        )

    # 3. Hard Gate: Nationality excluded
    student_nat = str(student.get("nationality") or "YE").upper()
    nat_rule = grant.get("nationality_rule")
    nat_verdict = evaluate_nationality(student_nat, nat_rule)
    if nat_verdict == "unclear" and student_nat == "YE" and grant.get("accepts_yemeni") in {"yes", "no"}:
        nat_verdict = str(grant.get("accepts_yemeni"))
    elif student_nat == "YE" and grant.get("accepts_yemeni") == "no":
        nat_verdict = "no"

    nat_quote = evidence.get("nationality_rule") or evidence.get("accepts_yemeni") or evidence.get("eligibility")
    if nat_verdict == "no":
        disqualifiers.append(
            DisqualifierItem(
                gate="nationality",
                reason_ar=f"جنسية الطالب ({student_nat}) غير مشمولة في شروط هذه المنحة.",
                reason_en=f"Student nationality ({student_nat}) is not eligible under grant nationality rules.",
                evidence_quote=nat_quote,
            )
        )

    # 4. Hard Gate: Allowed degree level mismatch
    allowed_degrees = grant.get("allowed_degrees") or []
    target_degree = student.get("target_degree")
    if allowed_degrees and target_degree and target_degree not in allowed_degrees:
        disqualifiers.append(
            DisqualifierItem(
                gate="degree_level",
                reason_ar=f"الدرجة المستهدفة ({target_degree}) غير متاحة في هذه المنحة ({', '.join(allowed_degrees)}).",
                reason_en=f"Target degree ({target_degree}) is not among allowed degrees ({', '.join(allowed_degrees)}).",
                evidence_quote=evidence.get("allowed_degrees") or evidence.get("description"),
            )
        )

    # Evaluate individual weighted criteria
    criteria: List[CriterionBreakdown] = []
    missing_hints: List[str] = []

    # C1: Nationality
    c_nat_status = "met" if nat_verdict == "yes" else ("not_met" if nat_verdict == "no" else "unknown")
    if c_nat_status == "unknown":
        missing_hints.append("تحقق من أهلية جنسيتك مباشرة في البوابة الرسمية لهذه المنحة.")
    criteria.append(
        CriterionBreakdown(
            key="nationality",
            status=c_nat_status,  # type: ignore[arg-type]
            weight=weights["nationality"],
            grant_value=(nat_rule or {}).get("mode", grant.get("accepts_yemeni")),
            student_value=student_nat,
            evidence_quote=nat_quote,
            reason_ar="الجنسية مشمولة في شروط المنحة."
            if c_nat_status == "met"
            else ("الجنسية غير مشمولة." if c_nat_status == "not_met" else "أهلية الجنسية غير محددة صراحةً في الصفحة."),
            reason_en="Nationality is eligible."
            if c_nat_status == "met"
            else ("Nationality excluded." if c_nat_status == "not_met" else "Nationality eligibility is unclear in source text."),
        )
    )

    # C2: Degree Level
    if not allowed_degrees:
        c_deg_status = "not_applicable"
        deg_ar, deg_en = "لم تحدد المنحة درجات مقيدة.", "Grant does not restrict degree levels."
    elif not target_degree:
        c_deg_status = "unknown"
        deg_ar, deg_en = "حدد الدرجة المستهدفة في ملفك.", "Set your target degree in your profile."
        missing_hints.append(f"حدّد الدرجة العلمية المستهدفة (المنحة تشمل: {', '.join(allowed_degrees)}).")
    elif target_degree in allowed_degrees:
        c_deg_status = "met"
        deg_ar, deg_en = "الدرجة المستهدفة مطابقة للمنحة.", "Target degree matches allowed degrees."
    else:
        c_deg_status = "not_met"
        deg_ar, deg_en = "الدرجة المستهدفة غير مشمولة.", "Target degree is outside allowed degrees."
    criteria.append(
        CriterionBreakdown(
            key="degree_level",
            status=c_deg_status,  # type: ignore[arg-type]
            weight=weights["degree_level"],
            grant_value=", ".join(allowed_degrees) if allowed_degrees else None,
            student_value=target_degree,
            evidence_quote=evidence.get("allowed_degrees") or evidence.get("description"),
            reason_ar=deg_ar,
            reason_en=deg_en,
        )
    )

    # C3: GPA
    grant_gpa_4 = grant.get("min_gpa_normalized_4")
    grant_gpa_str = (
        f"{grant.get('min_gpa_value')} ({grant.get('min_gpa_scale')})"
        if grant.get("min_gpa_value") is not None
        else None
    )
    student_gpa_4 = student.get("gpa_normalized_4")
    student_gpa_str = (
        f"{student.get('gpa_raw')} ({student.get('gpa_scale')})"
        if student.get("gpa_raw") is not None
        else None
    )
    if grant_gpa_4 is None:
        c_gpa_status = "not_applicable"
        gpa_ar, gpa_en = "لم تنص المنحة على حد أدنى رقمي للمعدل.", "No numeric GPA threshold stated."
    elif student_gpa_4 is None:
        c_gpa_status = "unknown"
        gpa_ar, gpa_en = "لم تُضف معدلك الدراسي بعد.", "Add your GPA to evaluate this condition."
        missing_hints.append(f"تشترط المنحة معدلاً لا يقل عن {grant_gpa_str}؛ أضف معدلك لحساب الاستيفاء.")
    elif float(student_gpa_4) >= float(grant_gpa_4):
        c_gpa_status = "met"
        gpa_ar, gpa_en = "معدلك يستوفي الحد الأدنى المعلن.", "Your GPA meets the minimum requirement."
    else:
        c_gpa_status = "not_met"
        gpa_ar, gpa_en = "معدلك أقل من الحد الأدنى المعلن.", "Your GPA is below the stated minimum."
    criteria.append(
        CriterionBreakdown(
            key="gpa",
            status=c_gpa_status,  # type: ignore[arg-type]
            weight=weights["gpa"],
            grant_value=grant_gpa_str,
            student_value=student_gpa_str,
            evidence_quote=evidence.get("min_gpa") or evidence.get("eligibility"),
            reason_ar=gpa_ar,
            reason_en=gpa_en,
        )
    )

    # C4: Language
    c_lang_status, g_lang_v, s_lang_v, lang_ar, lang_en, lang_hint = _evaluate_language(
        grant.get("language_requirements"),
        list(student.get("languages") or []),
    )
    if lang_hint:
        missing_hints.append(lang_hint)
    criteria.append(
        CriterionBreakdown(
            key="language",
            status=c_lang_status,  # type: ignore[arg-type]
            weight=weights["language"],
            grant_value=g_lang_v,
            student_value=s_lang_v,
            evidence_quote=evidence.get("language_requirements") or evidence.get("eligibility"),
            reason_ar=lang_ar,
            reason_en=lang_en,
        )
    )

    # C5: Field of study
    c_fld_status, g_fld_v, s_fld_v, fld_ar, fld_en = _evaluate_field_match(
        grant.get("fields_of_study"),
        student.get("major"),
        list(student.get("target_fields") or []),
    )
    if c_fld_status == "unknown":
        missing_hints.append("أضف تخصصك الدراسي أو اهتماماتك لمعرفة مدى تطابق التخصص.")
    criteria.append(
        CriterionBreakdown(
            key="field_of_study",
            status=c_fld_status,  # type: ignore[arg-type]
            weight=weights["field_of_study"],
            grant_value=g_fld_v,
            student_value=s_fld_v,
            evidence_quote=evidence.get("fields_of_study"),
            reason_ar=fld_ar,
            reason_en=fld_en,
        )
    )

    # C6: Work experience
    min_work = grant.get("min_work_years")
    student_work = student.get("work_experience_years")
    if min_work is None:
        c_wrk_status = "not_applicable"
        wrk_ar, wrk_en = "لم تشترط المنحة خبرة عملية محددة.", "No minimum work experience stated."
    elif student_work is None:
        c_wrk_status = "unknown"
        wrk_ar, wrk_en = "أضف سنوات الخبرة العملية للتحقق من الشرط.", "Add years of experience to evaluate this condition."
        missing_hints.append(f"تشترط المنحة {min_work} سنوات خبرة عملية على الأقل؛ أضف خبرتك.")
    elif float(student_work) >= float(min_work):
        c_wrk_status = "met"
        wrk_ar, wrk_en = "سنوات الخبرة تستوفي الحد المطلوب.", "Your work experience meets the minimum."
    else:
        c_wrk_status = "not_met"
        wrk_ar, wrk_en = "سنوات الخبرة أقل من المطلوب في المنحة.", "Work experience is below the stated minimum."
    criteria.append(
        CriterionBreakdown(
            key="work_experience",
            status=c_wrk_status,  # type: ignore[arg-type]
            weight=weights["work_experience"],
            grant_value=f"{min_work} years" if min_work is not None else None,
            student_value=f"{student_work} years" if student_work is not None else None,
            evidence_quote=evidence.get("min_work_years") or evidence.get("eligibility"),
            reason_ar=wrk_ar,
            reason_en=wrk_en,
        )
    )

    # C7: Age limit
    max_age = grant.get("max_age")
    student_age = student.get("age_years")
    if max_age is None:
        c_age_status = "not_applicable"
        age_ar, age_en = "لم تنص المنحة على حد أقصى للعمر.", "No maximum age limit stated."
    elif student_age is None:
        c_age_status = "unknown"
        age_ar, age_en = "أضف عمرك بالسنوات للتحقق من سقف العمر.", "Add your age to verify the age ceiling."
        missing_hints.append(f"تحدد المنحة سقفاً للعمر ({max_age} سنة)؛ أضف عمرك للتحقق.")
    elif int(student_age) <= int(max_age):
        c_age_status = "met"
        age_ar, age_en = "العمر ضمن الحد الأقصى المعلن.", "Your age is within the stated ceiling."
    else:
        c_age_status = "not_met"
        age_ar, age_en = "العمر يتجاوز الحد الأقصى المعلن.", "Your age exceeds the stated maximum."
    criteria.append(
        CriterionBreakdown(
            key="age",
            status=c_age_status,  # type: ignore[arg-type]
            weight=weights["age"],
            grant_value=str(max_age) if max_age is not None else None,
            student_value=str(student_age) if student_age is not None else None,
            evidence_quote=evidence.get("max_age") or evidence.get("eligibility"),
            reason_ar=age_ar,
            reason_en=age_en,
        )
    )

    # Percentages per D6
    applicable = [c for c in criteria if c.status != "not_applicable"]
    known = [c for c in applicable if c.status in {"met", "not_met"}]

    applicable_weight = sum(c.weight for c in applicable)
    known_weight = sum(c.weight for c in known)
    met_weight = sum(c.weight for c in known if c.status == "met")

    eligible = len(disqualifiers) == 0
    coverage_pct = round((known_weight / applicable_weight) * 100.0, 1) if applicable_weight > 0 else 100.0
    if not eligible or known_weight == 0:
        match_pct = 0.0
    else:
        match_pct = round((met_weight / known_weight) * 100.0, 1)

    return GrantMatchResult(
        grant_id=int(grant["id"]),
        title=str(grant["title"]),
        official_url=str(grant["official_url"]),
        deadline=deadline_date.isoformat() if deadline_date else None,
        host_country=grant.get("host_country"),
        funding_type=grant.get("funding_type"),
        featured_rank=grant.get("featured_rank"),
        accepts_yemeni=grant.get("accepts_yemeni") or "unclear",  # type: ignore[arg-type]
        nationality_rule=nat_rule,
        eligible=eligible,
        status="eligible" if eligible else "ineligible",
        disqualifiers=disqualifiers,
        match_percentage=match_pct,
        coverage_percentage=coverage_pct,
        weights_version=weights_version,
        criteria=criteria,
        missing_info_hints=missing_hints,
    )


def _match_sort_key(item: GrantMatchResult) -> tuple:
    # Sort: match_percentage DESC, coverage_percentage DESC, nearest deadline ASC (NULL last), featured_rank ASC
    has_deadline = 0 if item.deadline else 1
    dl_val = item.deadline or "9999-12-31"
    feat_val = item.featured_rank if item.featured_rank is not None else 999
    return (-item.match_percentage, -item.coverage_percentage, has_deadline, dl_val, feat_val, item.grant_id)


def compute_matches_for_student(
    student: Mapping[str, Any],
    grants: List[Mapping[str, Any]],
    *,
    reference_date: Optional[date] = None,
) -> MatchesListResponse:
    """Evaluate and rank all provided grants for a student profile."""
    weights_cfg = get_weights_config()
    gpa_cfg = get_gpa_scales_config()

    eligible: List[GrantMatchResult] = []
    ineligible: List[GrantMatchResult] = []

    for grant in grants:
        res = evaluate_grant_for_student(
            grant,
            student,
            weights_cfg=weights_cfg,
            reference_date=reference_date,
        )
        if res.eligible:
            eligible.append(res)
        else:
            ineligible.append(res)

    eligible.sort(key=_match_sort_key)

    return MatchesListResponse(
        eligible_grants=eligible,
        ineligible_grants=ineligible,
        total_evaluated=len(grants),
        weights_version=str(weights_cfg.get("version", "1.0")),
        gpa_scales_version=str(gpa_cfg.get("version", "1.0")),
        disclaimer_ar="تمثل نسبة التطابق عدد الشروط المنشورة المستوفاة من ملفك الحالي فقط، وليست احتمالاً للقبول النهائي.",
        disclaimer_en="Match percentage measures how many published grant conditions your stated profile meets, not admission odds.",
    )


def compute_matches_from_db(student: Mapping[str, Any]) -> MatchesListResponse:
    """Load published grants from DB and compute ranked matches for `student`."""
    with get_db() as db:
        published_rows = db.query(Grant).filter(Grant.status == GrantStatus.PUBLISHED).all()
        grant_dicts = [g.to_dict() for g in published_rows]
    return compute_matches_for_student(student, grant_dicts)
