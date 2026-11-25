"""Profile analysis capability (Spec Task 5).

Step 1: Computes deterministic findings in code across the student's matched grants.
Step 2: Calls `modules/llm/` ONCE with anonymized academic fields + findings.
Step 3: Drops any model statement that does not reference a real finding ID.
Fallback: Clearly labeled deterministic Arabic summary on LLMError or missing key.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from modules.llm.client import AsyncLLMClient, LLMError
from modules.llm.prompts import load_prompt
from modules.matching.schemas import (
    AnalysisStatement,
    DeterministicFinding,
    GrantMatchResult,
    LLMProfileAnalysisNarrative,
    MatchesListResponse,
    ProfileAnalysisResponse,
)

logger = logging.getLogger(__name__)


def build_deterministic_findings(
    student: Mapping[str, Any],
    matches: MatchesListResponse,
    grants_by_id: Optional[Mapping[int, Mapping[str, Any]]] = None,
) -> List[DeterministicFinding]:
    """Derive traceable deterministic findings from match breakdowns and required docs."""
    findings: List[DeterministicFinding] = []
    target_pool: Sequence[GrantMatchResult] = (
        matches.eligible_grants[:5] if matches.eligible_grants else matches.ineligible_grants[:5]
    )
    if not target_pool:
        return findings

    met_counts: Counter[str] = Counter()
    not_met_counts: Counter[str] = Counter()
    unknown_counts: Counter[str] = Counter()
    met_grants: Dict[str, List[str]] = {}
    not_met_grants: Dict[str, List[str]] = {}
    unknown_grants: Dict[str, List[str]] = {}

    for m in target_pool:
        for c in m.criteria:
            if c.status == "met":
                met_counts[c.key] += 1
                met_grants.setdefault(c.key, []).append(m.title)
            elif c.status == "not_met":
                not_met_counts[c.key] += 1
                not_met_grants.setdefault(c.key, []).append(m.title)
            elif c.status == "unknown":
                unknown_counts[c.key] += 1
                unknown_grants.setdefault(c.key, []).append(m.title)

    idx = 1

    # Disqualifier pattern if eligible pool is empty or reduced
    if matches.ineligible_grants:
        gate_counts = Counter(
            d.gate for m in matches.ineligible_grants for d in m.disqualifiers
        )
        for gate, cnt in gate_counts.most_common(2):
            fid = f"F{idx}"
            idx += 1
            findings.append(
                DeterministicFinding(
                    id=fid,
                    kind="weakness",
                    summary_ar=f"بوابة الأهلية ({gate}) استبعدت {cnt} منحة من النتائج المؤهلة.",
                    summary_en=f"Eligibility gate '{gate}' excluded {cnt} grants.",
                    count=cnt,
                    related_grants=[
                        m.title
                        for m in matches.ineligible_grants
                        if any(d.gate == gate for d in m.disqualifiers)
                    ][:4],
                )
            )

    label_ar_map = {
        "nationality": "الأهلية حسب الجنسية",
        "degree_level": "الدرجة العلمية المستهدفة",
        "gpa": "المعدل التراكمي",
        "language": "اختبار وإثبات اللغة",
        "field_of_study": "التخصص الدراسي",
        "work_experience": "سنوات الخبرة العملية",
        "age": "الحد الأقصى للعمر",
    }

    for key, cnt in met_counts.most_common(3):
        fid = f"F{idx}"
        idx += 1
        findings.append(
            DeterministicFinding(
                id=fid,
                kind="strength",
                summary_ar=f"شرط '{label_ar_map.get(key, key)}' مستوفى في {cnt} من أفضل المنح المطابقة.",
                summary_en=f"Criterion '{key}' is met across {cnt} top matching grants.",
                count=cnt,
                related_grants=met_grants.get(key, [])[:4],
            )
        )

    for key, cnt in not_met_counts.most_common(3):
        fid = f"F{idx}"
        idx += 1
        findings.append(
            DeterministicFinding(
                id=fid,
                kind="weakness",
                summary_ar=f"شرط '{label_ar_map.get(key, key)}' غير مستوفى في {cnt} من أعلى المنح.",
                summary_en=f"Criterion '{key}' is unmet across {cnt} top grants.",
                count=cnt,
                related_grants=not_met_grants.get(key, [])[:4],
            )
        )

    for key, cnt in unknown_counts.most_common(3):
        fid = f"F{idx}"
        idx += 1
        findings.append(
            DeterministicFinding(
                id=fid,
                kind="gap",
                summary_ar=f"نقص بيانات '{label_ar_map.get(key, key)}' يترك النتيجة غير محسومة في {cnt} منح.",
                summary_en=f"Missing profile data for '{key}' leaves {cnt} grants partially unknown.",
                count=cnt,
                related_grants=unknown_grants.get(key, [])[:4],
            )
        )

    # Required documents across top matches
    if grants_by_id:
        doc_counter: Counter[str] = Counter()
        for m in target_pool:
            g = grants_by_id.get(m.grant_id) or {}
            for doc in g.get("required_documents") or []:
                d_clean = str(doc).strip()
                if d_clean:
                    doc_counter[d_clean] += 1
        top_docs = doc_counter.most_common(4)
        if top_docs:
            fid = f"F{idx}"
            idx += 1
            doc_str = "، ".join(f"{name} ({cnt})" for name, cnt in top_docs)
            findings.append(
                DeterministicFinding(
                    id=fid,
                    kind="documents",
                    summary_ar=f"أكثر الوثائق المطلوبة تكراراً في هذه المنح: {doc_str}.",
                    summary_en=f"Most commonly required documents: {', '.join(d for d, _ in top_docs)}.",
                    count=len(top_docs),
                    related_grants=[m.title for m in target_pool[:3]],
                )
            )

    return findings


def _anonymized_academic_context(student: Mapping[str, Any]) -> Dict[str, Any]:
    """Project ONLY non-identifying academic attributes for LLM narration (D12)."""
    return {
        "nationality_code": student.get("nationality"),
        "target_degree": student.get("target_degree"),
        "current_degree": student.get("current_degree"),
        "major": student.get("major"),
        "gpa_normalized_4": student.get("gpa_normalized_4"),
        "languages": [
            {
                "language": l.get("language"),
                "test_name": l.get("test_name"),
                "score": l.get("score"),
                "self_assessed_cefr": l.get("self_assessed_cefr"),
                "is_self_assessed": l.get("is_self_assessed"),
            }
            for l in (student.get("languages") or [])
        ],
        "work_experience_years": student.get("work_experience_years"),
        "publications_count": student.get("publications_count", 0),
        "funding_need": student.get("funding_need"),
        "target_countries": student.get("target_countries") or [],
        "experience_notes": student.get("experience_notes") or [],
    }


def _filter_grounded_statements(
    statements: List[AnalysisStatement],
    valid_ids: set[str],
) -> Tuple[List[AnalysisStatement], int]:
    kept: List[AnalysisStatement] = []
    dropped = 0
    for st in statements:
        matching_ids = [fid for fid in st.finding_ids if fid in valid_ids]
        if not matching_ids:
            dropped += 1
            continue
        kept.append(AnalysisStatement(text_ar=st.text_ar, finding_ids=matching_ids))
    return kept, dropped


def build_deterministic_fallback_response(
    findings: List[DeterministicFinding],
    *,
    retryable: bool = False,
    notice_ar: Optional[str] = None,
    notice_en: Optional[str] = None,
) -> ProfileAnalysisResponse:
    """Build an honest deterministic-only Arabic analysis when the LLM is unavailable."""
    strengths = [
        AnalysisStatement(text_ar=f.summary_ar, finding_ids=[f.id])
        for f in findings
        if f.kind == "strength"
    ]
    weaknesses = [
        AnalysisStatement(text_ar=f.summary_ar, finding_ids=[f.id])
        for f in findings
        if f.kind == "weakness"
    ]
    improvements = [
        AnalysisStatement(text_ar=f.summary_ar, finding_ids=[f.id])
        for f in findings
        if f.kind in {"gap", "documents"}
    ]
    summary = (
        "تم إنشاء هذا التحليل من القواعد الحتمية والوثائق المنشورة فقط دون استدعاء نموذج الذكاء الاصطناعي."
        if findings
        else "أكمل بيانات ملفك الشخصي لعرض تحليل مفصل لنقاط القوة والفجوات."
    )
    return ProfileAnalysisResponse(
        analysis_mode="deterministic_fallback",
        prompt_version=None,
        retryable=retryable,
        fallback_notice_ar=notice_ar
        or "تحليل حتمي مباشر من نتائج المطابقة (خدمة التلخيص الذكي غير متاحة حالياً).",
        fallback_notice_en=notice_en
        or "Deterministic analysis computed strictly from your matches (AI narration currently unavailable).",
        findings=findings,
        summary_ar=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        improvement_areas=improvements,
        dropped_ungrounded_count=0,
    )


async def generate_profile_analysis(
    student: Mapping[str, Any],
    matches: MatchesListResponse,
    grants_by_id: Optional[Mapping[int, Mapping[str, Any]]] = None,
    llm_client: Optional[AsyncLLMClient] = None,
) -> ProfileAnalysisResponse:
    """Run deterministic findings + ONE structured LLM call with finding-ID enforcement."""
    findings = build_deterministic_findings(student, matches, grants_by_id=grants_by_id)
    if not findings:
        return build_deterministic_fallback_response(findings, retryable=False)

    if llm_client is None:
        return build_deterministic_fallback_response(findings, retryable=True)

    prompt_text, prompt_version = load_prompt("profile_analysis")
    payload = {
        "academic_profile": _anonymized_academic_context(student),
        "findings": [f.model_dump() for f in findings],
    }
    messages = [
        {"role": "system", "content": prompt_text},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]

    try:
        narrative = await llm_client.structured(
            messages,
            LLMProfileAnalysisNarrative,
            prompt_version=prompt_version,
            max_tokens=700,
            temperature=0.1,
        )
    except LLMError as exc:
        logger.warning("profile_analysis fallback triggered: %s", exc)
        return build_deterministic_fallback_response(
            findings,
            retryable=True,
            notice_ar="تعذر الاتصال بخدمة التلخيص الذكي الآن؛ تم عرض التحليل الحتمي الموثق بالكود ويمكنك إعادة المحاولة.",
            notice_en="AI summary service unavailable right now; showing deterministic analysis. You can retry shortly.",
        )

    valid_ids = {f.id for f in findings}
    s_kept, d1 = _filter_grounded_statements(narrative.strengths, valid_ids)
    w_kept, d2 = _filter_grounded_statements(narrative.weaknesses, valid_ids)
    i_kept, d3 = _filter_grounded_statements(narrative.improvement_areas, valid_ids)
    total_dropped = d1 + d2 + d3

    return ProfileAnalysisResponse(
        analysis_mode="llm_grounded",
        prompt_version=prompt_version,
        retryable=False,
        findings=findings,
        summary_ar=narrative.summary_ar,
        strengths=s_kept,
        weaknesses=w_kept,
        improvement_areas=i_kept,
        dropped_ungrounded_count=total_dropped,
    )
