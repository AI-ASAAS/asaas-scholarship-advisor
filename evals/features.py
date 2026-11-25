"""Feature adapters registered into `evals.run_eval.FEATURES`."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from core.config import settings
from modules.llm.client import AsyncLLMClient
from modules.matching.gpa import normalize_gpa_to_4
from modules.matching.nationalities import evaluate_nationality
from utils.evidence_check import verify_evidence
from utils.llm_extractor import GrantExtractionSchema, extract_grant_from_text_async

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "seed" / "fixtures"

# Deterministic stub responses used ONLY when LLM_API_KEY is absent from environment.
_STUB_EXTRACTIONS: Dict[str, Dict[str, Any]] = {}


def _build_stub_responses() -> Dict[str, Dict[str, Any]]:
    from seed.seed_db import VERIFIED_TOP10_BASELINE
    from seed.structured_backfill import build_verified_backfill_map

    backfill_map = build_verified_backfill_map()
    by_fixture: Dict[str, Dict[str, Any]] = {}
    for idx, entry in enumerate(VERIFIED_TOP10_BASELINE, start=1):
        url = entry["official_url"]
        bf = backfill_map.get(url, {})
        slug = (
            url.replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
            .replace("www.", "")
            .replace(".", "_")
            .replace("-", "_")
        )
        fname = f"{idx:02d}_{slug}.txt"
        ev = dict(entry.get("evidence") or {})
        ev.update(bf.get("evidence_additions") or {})
        ev["title"] = entry["title"]
        # Seed baseline deadline quote may be partial ("20 February"); include full ISO if needed
        dl_iso = entry["deadline"].isoformat() if entry.get("deadline") else None
        if dl_iso:
            ev["deadline"] = dl_iso
        nat = bf.get("nationality_rule") or {"mode": "unclear", "countries": [], "groups": []}
        by_fixture[fname] = {
            "title": entry["title"],
            "description": entry.get("description"),
            "eligibility": entry.get("eligibility"),
            "criteria": entry.get("criteria"),
            "fields_of_study": entry.get("fields_of_study"),
            "funding": entry.get("funding"),
            "required_documents": entry.get("required_documents"),
            "deadline": dl_iso,
            "how_to_apply": entry.get("how_to_apply"),
            "accepts_yemeni": entry["accepts_yemeni"].value,
            "provider_name": bf.get("provider_name"),
            "host_country": bf.get("host_country"),
            "allowed_degrees": bf.get("allowed_degrees"),
            "min_gpa_value": bf.get("min_gpa_value"),
            "min_gpa_scale": bf.get("min_gpa_scale"),
            "language_requirements": bf.get("language_requirements"),
            "nationality_rule": {
                "mode": nat.get("mode", "unclear"),
                "countries": nat.get("countries", []),
                "groups": nat.get("groups", []),
            },
            "min_work_years": bf.get("min_work_years"),
            "max_age": bf.get("max_age"),
            "funding_type": bf.get("funding_type") or "unknown",
            "evidence": ev,
        }
    return by_fixture


class _StubAsyncLLMClient:
    """Stub AsyncLLMClient returning deterministic JSON payloads when no API key exists."""

    def __init__(self, payloads: Dict[str, Dict[str, Any]]) -> None:
        self._payloads = payloads

    async def structured(self, messages, schema, *, prompt_version, **options):
        user_msg = str(messages[-1].get("content") or "")
        for marker, payload in self._payloads.items():
            if marker in user_msg:
                return schema.model_validate(payload)
        raise RuntimeError("Stub client has no matching payload for input text.")


def _inline_stub_payloads() -> Dict[str, Dict[str, Any]]:
    payloads: Dict[str, Dict[str, Any]] = {}
    for _fname, rec in _build_stub_responses().items():
        payloads[rec["title"]] = rec

    payloads["Nordic Open Sustainability Grant"] = {
        "title": "Nordic Open Sustainability Grant",
        "description": "Tuition and stipend award for master's students in sustainability.",
        "eligibility": ["Open to students worldwide; applications reviewed on a rolling basis."],
        "deadline": None,
        "accepts_yemeni": "yes",
        "host_country": "SE",
        "allowed_degrees": ["master"],
        "nationality_rule": {"mode": "all", "countries": [], "groups": []},
        "funding_type": "full",
        "evidence": {
            "title": "Nordic Open Sustainability Grant",
            "description": "Tuition and stipend award for master's students in sustainability.",
            "eligibility": "Open to students worldwide",
            "host_country": "Sweden",
            "allowed_degrees": "master's students",
            "nationality_rule": "Open to students worldwide",
            "funding_type": "Tuition and stipend award",
        },
    }
    payloads["Global Innovators Fellowship"] = {
        "title": "Global Innovators Fellowship",
        "description": "Research fellowship open to citizens of all nationalities worldwide.",
        "eligibility": ["Open to citizens of all nationalities worldwide."],
        "deadline": "2027-09-01",
        "accepts_yemeni": "yes",
        "allowed_degrees": ["phd"],
        "nationality_rule": {"mode": "all", "countries": [], "groups": []},
        "funding_type": "stipend",
        "evidence": {
            "title": "Global Innovators Fellowship",
            "description": "Research fellowship open to citizens of all nationalities worldwide.",
            "eligibility": "Open to citizens of all nationalities worldwide.",
            "deadline": "2027-09-01",
            "allowed_degrees": "PhD candidates",
            "nationality_rule": "Open to citizens of all nationalities worldwide.",
            "funding_type": "monthly stipend",
        },
    }
    payloads["Pacific Exchange Scholarship 2027"] = {
        "title": "Pacific Exchange Scholarship 2027",
        "description": "International exchange scholarship.",
        "eligibility": ["Open to international applicants except citizens of Yemen who are explicitly excluded for this cycle."],
        "deadline": "2027-08-20",
        "accepts_yemeni": "no",
        "allowed_degrees": ["bachelor"],
        "nationality_rule": {"mode": "exclude", "countries": ["YE"], "groups": []},
        "funding_type": "partial",
        "evidence": {
            "title": "Pacific Exchange Scholarship 2027",
            "eligibility": "except citizens of Yemen who are explicitly excluded for this cycle.",
            "deadline": "2027-08-20",
            "allowed_degrees": "undergraduate bachelor degree",
            "nationality_rule": "except citizens of Yemen who are explicitly excluded for this cycle.",
            "funding_type": "partial tuition grant",
        },
    }
    payloads["Kyoto Science Fellowship"] = {
        "title": "Kyoto Science Fellowship",
        "description": "Graduate research fellowship hosted in Japan.",
        "eligibility": ["Restricted to citizens of Japan holding a bachelor degree."],
        "funding": "Partial tuition waiver of 50%.",
        "deadline": "2027-04-10",
        "accepts_yemeni": "no",
        "host_country": "JP",
        "allowed_degrees": ["master"],
        "nationality_rule": {"mode": "include", "countries": ["JP"], "groups": []},
        "funding_type": "partial",
        "evidence": {
            "title": "Kyoto Science Fellowship",
            "description": "Graduate research fellowship hosted in Japan.",
            "eligibility": "Restricted to citizens of Japan",
            "funding": "Partial tuition waiver of 50%.",
            "deadline": "2027-04-10",
            "host_country": "Japan",
            "allowed_degrees": "Master's applicants",
            "nationality_rule": "Restricted to citizens of Japan",
            "funding_type": "Partial tuition waiver of 50%.",
        },
    }
    payloads["منحة التميز بجامعة المستقبل"] = {
        "title": "منحة التميز بجامعة المستقبل",
        "description": "منحة دراسية كاملة لدرجتي البكالوريوس والماجستير.",
        "eligibility": ["متاحة لجميع الجنسيات حول العالم.", "يشترط معدل تراكمي لا يقل عن 85%."],
        "deadline": "2027-05-15",
        "accepts_yemeni": "yes",
        "allowed_degrees": ["bachelor", "master"],
        "min_gpa_value": 85.0,
        "min_gpa_scale": "100",
        "nationality_rule": {"mode": "all", "countries": [], "groups": []},
        "funding_type": "full",
        "evidence": {
            "title": "منحة التميز بجامعة المستقبل",
            "description": "منحة دراسية كاملة لدرجتي البكالوريوس والماجستير.",
            "eligibility": "متاحة لجميع الجنسيات حول العالم.",
            "allowed_degrees": "لدرجتي البكالوريوس والماجستير",
            "min_gpa": "معدل تراكمي لا يقل عن 85%",
            "nationality_rule": "متاحة لجميع الجنسيات حول العالم.",
            "funding_type": "منحة دراسية كاملة",
            "deadline": "2027-05-15",
        },
    }
    return payloads


def _load_case_page_text(case_input: Dict[str, Any]) -> str:
    if case_input.get("fixture"):
        return (FIXTURES_DIR / str(case_input["fixture"])).read_text(encoding="utf-8")
    return str(case_input.get("page_text") or "")


async def eval_extraction(case_input: Dict[str, Any], *, live: Optional[bool] = None) -> Dict[str, Any]:
    """Run extraction on a single eval case and verify evidence in Python code."""
    page_text = _load_case_page_text(case_input)
    api_key = (os.getenv("LLM_API_KEY") or settings.LLM_API_KEY or "").strip()
    use_live = bool(api_key) if live is None else live

    if use_live:
        models = settings.resolved_llm_models
        base_url = settings.resolved_llm_base_url
        extra_body = settings.resolved_llm_extra_body
        timeout_sec = settings.LLM_TIMEOUT_SECONDS
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_sec, connect=min(5.0, timeout_sec)),
        ) as http:
            client = AsyncLLMClient(
                http=http,
                models=models,
                extra_body=extra_body,
                default_max_tokens=settings.LLM_MAX_TOKENS,
                response_format_mode=settings.LLM_RESPONSE_FORMAT_MODE,
                configured=True,
            )
            extraction: GrantExtractionSchema = await extract_grant_from_text_async(page_text, client)
    else:
        stub_client = _StubAsyncLLMClient(_inline_stub_payloads())
        extraction = await extract_grant_from_text_async(page_text, stub_client)  # type: ignore[arg-type]

    raw_fields = {
        "title": extraction.title,
        "description": extraction.description,
        "eligibility": extraction.eligibility,
        "criteria": extraction.criteria,
        "fields_of_study": extraction.fields_of_study,
        "funding": extraction.funding,
        "required_documents": extraction.required_documents,
        "deadline": extraction.deadline,
        "how_to_apply": extraction.how_to_apply,
        "accepts_yemeni": extraction.accepts_yemeni,
        "provider_name": extraction.provider_name,
        "host_country": extraction.host_country,
        "allowed_degrees": extraction.allowed_degrees,
        "min_gpa_value": extraction.min_gpa_value,
        "min_gpa_scale": extraction.min_gpa_scale,
        "language_requirements": (
            [item.model_dump() for item in extraction.language_requirements]
            if extraction.language_requirements
            else None
        ),
        "nationality_rule": extraction.nationality_rule.model_dump(),
        "min_work_years": extraction.min_work_years,
        "max_age": extraction.max_age,
        "funding_type": extraction.funding_type,
    }

    sanitized, field_verification = verify_evidence(
        fields=raw_fields,
        evidence=extraction.evidence,
        page_text=page_text,
    )
    sanitized["min_gpa_normalized_4"] = normalize_gpa_to_4(
        sanitized.get("min_gpa_value"), sanitized.get("min_gpa_scale")
    )
    sanitized["nationality_ye"] = evaluate_nationality("YE", sanitized.get("nationality_rule"))
    sanitized["field_verification"] = field_verification
    sanitized["evidence"] = extraction.evidence
    return sanitized


class _CapturingStubAnalysisClient:
    """Stub AsyncLLMClient that records the exact serialized messages sent to it."""

    def __init__(self) -> None:
        self.captured_requests: list[dict[str, Any]] = []

    async def structured(self, messages, schema, *, prompt_version, **options):
        user_payload = json.loads(str(messages[-1]["content"]))
        self.captured_requests.append({"messages": messages, "prompt_version": prompt_version})
        findings = user_payload.get("findings") or []
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for f in findings:
            by_kind.setdefault(str(f["kind"]), []).append(f)

        return schema.model_validate(
            {
                "summary_ar": "تحليل أولي لملفك الأكاديمي استناداً إلى نتائج المطابقة الموثقة.",
                "strengths": [
                    {"text_ar": f["summary_ar"], "finding_ids": [f["id"]]}
                    for f in by_kind.get("strength", [])
                ],
                "weaknesses": [
                    {"text_ar": f["summary_ar"], "finding_ids": [f["id"]]}
                    for f in by_kind.get("weakness", [])
                ],
                "improvement_areas": [
                    {"text_ar": f["summary_ar"], "finding_ids": [f["id"]]}
                    for f in (by_kind.get("gap", []) + by_kind.get("documents", []))
                ],
            }
        )


class _CapturingLiveLLMClient(AsyncLLMClient):
    """Wraps AsyncLLMClient to capture the exact JSON request sent to the model provider."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captured_requests: list[dict[str, Any]] = []

    async def structured(self, messages, schema, *, prompt_version, **options):
        self.captured_requests.append({"messages": messages, "prompt_version": prompt_version})
        return await super().structured(messages, schema, prompt_version=prompt_version, **options)


async def eval_profile_analysis(
    case_input: Dict[str, Any],
    *,
    live: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run deterministic matching + profile_analysis and return result + captured LLM input."""
    from datetime import date
    from modules.matching.analysis import generate_profile_analysis
    from modules.matching.service import compute_matches_for_student
    from modules.students.service import scrub_pii_notes
    from seed.seed_db import VERIFIED_TOP10_BASELINE
    from seed.structured_backfill import build_verified_backfill_map

    student_raw = dict(case_input.get("student") or {})
    if "experience_notes" in student_raw and isinstance(student_raw["experience_notes"], list):
        student_raw["experience_notes"] = scrub_pii_notes(student_raw["experience_notes"])

    bf_map = build_verified_backfill_map()
    seed_grants = []
    for idx, entry in enumerate(VERIFIED_TOP10_BASELINE, 1):
        rec = dict(entry)
        rec["id"] = idx
        rec["status"] = "published"
        rec["accepts_yemeni"] = entry["accepts_yemeni"].value
        bf = bf_map[entry["official_url"]]
        rec.update(bf)
        rec["evidence"] = {**(entry.get("evidence") or {}), **(bf.get("evidence_additions") or {})}
        seed_grants.append(rec)

    grants_by_id = {g["id"]: g for g in seed_grants}
    matches = compute_matches_for_student(student_raw, seed_grants, reference_date=date(2026, 6, 1))

    api_key = (os.getenv("LLM_API_KEY") or settings.LLM_API_KEY or "").strip()
    use_live = bool(api_key) if live is None else live

    if use_live:
        async with httpx.AsyncClient(
            base_url=settings.resolved_llm_base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS, connect=5.0),
        ) as http:
            client = _CapturingLiveLLMClient(
                http=http,
                models=settings.resolved_llm_models,
                extra_body=settings.resolved_llm_extra_body,
                default_max_tokens=settings.LLM_MAX_TOKENS,
                response_format_mode=settings.LLM_RESPONSE_FORMAT_MODE,
                configured=True,
            )
            res = await generate_profile_analysis(
                student_raw, matches, grants_by_id=grants_by_id, llm_client=client
            )
            captured = client.captured_requests
    else:
        stub = _CapturingStubAnalysisClient()
        res = await generate_profile_analysis(
            student_raw, matches, grants_by_id=grants_by_id, llm_client=stub  # type: ignore[arg-type]
        )
        captured = stub.captured_requests

    out = res.model_dump()
    out["_captured_llm_input"] = captured
    out["_raw_student_pii_markers"] = [
        val
        for k in ("session_id", "email", "phone", "national_id")
        if (val := case_input.get("student", {}).get(k))
    ]
    return out


class _CapturingLiveChatLLM(AsyncLLMClient):
    """Wraps AsyncLLMClient to record chat requests and options for advisor evals."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captured_requests: list[dict[str, Any]] = []

    async def chat(self, messages, *, prompt_version, max_tokens=None, temperature=0.2, **options):
        self.captured_requests.append(
            {
                "messages": messages,
                "prompt_version": prompt_version,
                "max_tokens": max_tokens,
                "options": {k: v for k, v in options.items() if k != "tools"},
            }
        )
        return await super().chat(
            messages,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
            temperature=temperature,
            **options,
        )


class _StubAdvisorLLMClient:
    """Deterministic stub chat client for offline `advisor --stub` verification."""

    def __init__(self) -> None:
        self._step = 0

    async def chat(self, messages, *, prompt_version, max_tokens=None, temperature=0.2, **options):
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = str(msg.get("content") or "")
                break
        last_msg = messages[-1]

        # Step 0: pick appropriate tool call
        if last_msg.get("role") != "tool":
            q_low = last_user.lower()
            if "قارن بين" in q_low:
                fn, args = "compare_grants", {"grant_ids": [1, 2]}
            elif "زحل للفضاء" in q_low:
                fn, args = "get_grant", {"title_query": "زحل للفضاء"}
            elif "polaris" in q_low:
                fn, args = "get_grant", {"title_query": "Polaris"}
            elif "stipendium" in q_low or "hungaricum" in q_low:
                fn, args = "get_grant", {"title_query": "Stipendium Hungaricum"}
            elif "خطة التقديم" in q_low or "خطتي" in q_low or "إنجازي في خطة" in q_low:
                fn, args = "get_my_plan", {}
            elif "3.85" in q_low:
                fn, args = "propose_profile_update", {"gpa_raw": "3.85", "gpa_scale": "4.0"}
            elif "7.5" in q_low or "ielts" in q_low:
                fn, args = (
                    "propose_profile_update",
                    {"add_language": {"language": "English", "test_name": "IELTS", "score": 7.5}},
                )
            elif any(w in q_low for w in ("نسبة", "نواقص", "ملفي", "جنسيتي", "تضمن", "التخصص الذي ذكرته")):
                fn, args = "match_grants", {"limit": 5}
            elif "تشيفنينج" in q_low or "chevening" in q_low or "chevenig" in q_low:
                fn, args = "search_grants", {"query": "Chevening"}
            elif "daad" in q_low:
                fn, args = "search_grants", {"query": "DAAD"}
            elif "بريطانيا" in q_low:
                fn, args = "search_grants", {"country": "GB", "degree": "master"}
            elif any(w in q_low for w in ("لجوء", "صداع", "حمى")):
                fn, args = "search_grants", {"query": "nonexistent-offtopic"}
            else:
                fn, args = "search_grants", {"limit": 5}

            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "stub_call_1",
                        "type": "function",
                        "function": {"name": fn, "arguments": json.dumps(args, ensure_ascii=False)},
                    }
                ],
            }

        # Step 1: produce grounded reply from tool output
        tool_payload = json.loads(str(last_msg.get("content") or "{}"))
        data = tool_payload.get("untrusted_tool_data") or {}
        q_low = last_user.lower()

        if "error" in data and "not available or permitted" in str(data["error"]):
            return {"role": "assistant", "content": "عذراً، الوصول إلى ملفك الشخصي يتطلب موافقة الخصوصية أولاً."}
        if any(w in q_low for w in ("صداع", "حمى", "لجوء")):
            return {
                "role": "assistant",
                "content": "عذراً، هذا المساعد مخصّص فقط للمنح الدراسية والاستشارات الأكاديمية المرتبطة بها. كيف أساعدك في ملفك أو منحك؟",
            }
        if data.get("status") == "proposal shown to the user; nothing has been saved yet":
            return {
                "role": "assistant",
                "content": "أعددت لك بطاقة اقتراح لتعديل ملفك، ولن يتم حفظ التغيير إلا بعد تأكيدك.",
            }
        if data.get("has_plan") is True and "items" in data:
            titles = [f"#{i['priority_rank']} {i['title']} ({i.get('deadline') or ''})" for i in data["items"][:3]]
            return {
                "role": "assistant",
                "content": f"خطتك الحالية تضم: {' | '.join(titles)} بنسبة إنجاز {data.get('overall_progress_percentage', 0)}%.",
            }
        if data.get("available") is False or data.get("has_plan") is False:
            return {
                "role": "assistant",
                "content": "خطة التقديم الشخصية لديك فارغة حالياً؛ يمكنك إضافة المنح من صفحة التطابق.",
            }
        if data.get("found") is False:
            return {
                "role": "assistant",
                "content": "عذراً، هذه المنحة غير متوفرة في قائمة المنح المعتمدة بالمنصة. أنصحك باستخدام صفحة البحث الخارجي.",
            }
        if "grant" in data:
            g = data["grant"]
            return {
                "role": "assistant",
                "content": f"منحة {g['title']} (الرابط الرسمي: {g['official_url']}) متاحة بموعد نهائي {g.get('deadline') or 'غير محدد'} وتنبيه للتحقق من الموقع الرسمي.",
            }
        if "eligible_grants" in data:
            elig = data.get("eligible_grants") or []
            if elig:
                top = elig[0]
                return {
                    "role": "assistant",
                    "content": (
                        f"بناءً على ملفك الحالي، أعلى منحة مطابقة هي {top['title']} بنسبة تطابق {top['match_percentage']}% "
                        f"(الرابط الرسمي: {top['official_url']}). يرجى التحقق من الموعد النهائي عبر الموقع الرسمي، ولا نضمن القبول."
                    ),
                }
            return {"role": "assistant", "content": "لا توجد منح مؤهلة تماماً لملفك في القائمة الحالية."}
        grants = data.get("grants") or []
        if grants:
            lines = [f"{g['title']} ({g['official_url']})" for g in grants[:3]]
            return {
                "role": "assistant",
                "content": "إليك المنح الموثقة في المنصة: " + " | ".join(lines) + ". يُرجى دائماً مراجعة الموعد النهائي من الرابط الرسمي.",
            }
        return {
            "role": "assistant",
            "content": "عذراً، لم أجد منحة مطابقة في المنصة؛ يمكنك تجربة ميزة البحث الخارجي.",
        }


async def eval_advisor(case_input: Dict[str, Any], *, live: Optional[bool] = None) -> Dict[str, Any]:
    """Evaluate the scoped scholarship advisor assistant against an isolated temp DB."""
    import tempfile
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import core.db as core_db
    from core.models import Grant, GrantStatus, StudentConsent, StudentProfile, StudentSession, YemeniEligibilityStatus
    from migrations.runner import run_migrations
    from modules.assistant.schemas import AssistantAskRequest
    from modules.assistant.service import AssistantService
    from modules.auth.schemas import StudentPrincipal
    from modules.students.schemas import CURRENT_CONSENT_VERSION, StudentProfileUpsertRequest
    from modules.students.service import StudentService
    from seed.seed_db import seed_database

    prev_engine = core_db.engine
    prev_session_local = core_db.SessionLocal

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "eval_advisor.db"
        eval_engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        eval_session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=eval_engine,
            expire_on_commit=False,
        )
        core_db.engine = eval_engine
        core_db.SessionLocal = eval_session_local
        try:
            run_migrations(eval_engine)
            seed_database(publish_all=True)

            inject = case_input.get("inject_grant")
            if inject:
                with core_db.get_db() as db:
                    db.add(
                        Grant(
                            title=inject["title"],
                            official_url=inject["official_url"],
                            description=inject["description"],
                            accepts_yemeni=YemeniEligibilityStatus.YES,
                            nationality_rule={"mode": "all", "countries": [], "groups": []},
                            allowed_degrees=["master"],
                            funding_type="full",
                            status=GrantStatus.PUBLISHED,
                            featured_rank=11,
                        )
                    )
                    db.flush()

            has_consent = bool(case_input.get("has_consent", False))
            session_id = "eval-student-a"
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with core_db.get_db() as db:
                db.add(
                    StudentSession(
                        id=session_id,
                        token_hash="eval-hash-a",
                        created_at=now,
                        last_seen_at=now,
                        expires_at=now.replace(year=now.year + 1),
                    )
                )
                if has_consent:
                    db.add(
                        StudentConsent(
                            session_id=session_id,
                            consent_version=CURRENT_CONSENT_VERSION,
                            scopes_json={"profile_storage": True, "ai_processing": True},
                            accepted_at=now,
                        )
                    )
                if case_input.get("other_student"):
                    db.add(
                        StudentSession(
                            id="eval-student-b",
                            token_hash="eval-hash-b",
                            created_at=now,
                            last_seen_at=now,
                            expires_at=now.replace(year=now.year + 1),
                        )
                    )
                    db.add(
                        StudentConsent(
                            session_id="eval-student-b",
                            consent_version=CURRENT_CONSENT_VERSION,
                            scopes_json={"profile_storage": True},
                            accepted_at=now,
                        )
                    )
                db.flush()

            student_svc = StudentService()
            before_snapshot = None
            if has_consent and case_input.get("student"):
                prof_req = StudentProfileUpsertRequest(**case_input["student"])
                saved = student_svc.save_profile(session_id, prof_req)
                before_snapshot = saved.model_dump()
            if case_input.get("other_student"):
                student_svc.save_profile(
                    "eval-student-b",
                    StudentProfileUpsertRequest(**case_input["other_student"]),
                )

            if has_consent and case_input.get("plan_grant_titles"):
                from modules.plans.schemas import PlanAddGrantRequest
                from modules.plans.service import PlansService

                plan_svc = PlansService()
                with core_db.get_db() as db:
                    for title_q in case_input["plan_grant_titles"]:
                        g = (
                            db.query(Grant)
                            .filter(Grant.status == GrantStatus.PUBLISHED, Grant.title.contains(title_q))
                            .first()
                        )
                        if g:
                            plan_svc.add_grant(
                                session_id=session_id,
                                request=PlanAddGrantRequest(grant_id=g.id, allow_ineligible=True),
                            )

            principal = StudentPrincipal(
                session_id=session_id,
                authenticated=True,
                has_consent=has_consent,
            )
            req = AssistantAskRequest(messages=case_input["messages"])

            api_key = (os.getenv("LLM_API_KEY") or settings.LLM_API_KEY or "").strip()
            use_live = bool(api_key) if live is None else live

            if use_live:
                async with httpx.AsyncClient(
                    base_url=settings.resolved_llm_base_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS, connect=5.0),
                ) as http:
                    client = _CapturingLiveChatLLM(
                        http=http,
                        models=settings.resolved_llm_models,
                        extra_body=settings.resolved_llm_extra_body,
                        default_max_tokens=settings.ASSISTANT_MAX_TOKENS,
                        response_format_mode=settings.LLM_RESPONSE_FORMAT_MODE,
                        configured=True,
                    )
                    resp, trace = await AssistantService(client).ask_with_trace(
                        principal, req, persist=False
                    )
                    captured = client.captured_requests
            else:
                stub = _StubAdvisorLLMClient()
                resp, trace = await AssistantService(stub).ask_with_trace(  # type: ignore[arg-type]
                    principal, req, persist=False
                )
                captured = []

            after_prof = student_svc.get_profile(session_id) if has_consent else None
            after_snapshot = after_prof.model_dump() if after_prof else None
            if before_snapshot:
                before_snapshot.pop("updated_at", None)
            if after_snapshot:
                after_snapshot.pop("updated_at", None)

            return {
                "reply": resp.reply,
                "attachments": resp.attachments,
                "tools_used": trace.get("tools_used", []),
                "tool_outputs": trace.get("tool_outputs", []),
                "precheck_refused": bool(trace.get("precheck_refused", False)),
                "stopped_at_max_steps": bool(trace.get("stopped_at_max_steps", False)),
                "has_proposal": any(a.get("type") == "proposal" for a in resp.attachments),
                "profile_changed_in_db": before_snapshot != after_snapshot,
                "_captured_llm_input": captured,
            }
        finally:
            core_db.engine = prev_engine
            core_db.SessionLocal = prev_session_local
            eval_engine.dispose()


class _StubDocumentsLLMClient:
    """Offline deterministic stub returning schema-valid document drafts."""

    def __init__(self) -> None:
        self._configured = True
        self.captured_requests: list[dict[str, Any]] = []

    async def structured(self, messages, schema, *, prompt_version, **options):
        self.captured_requests.append({"messages": messages, "prompt_version": prompt_version})
        user_payload = json.loads(str(messages[-1]["content"]))
        doc_type = user_payload.get("doc_type")
        lang = user_payload.get("target_language", "ar")
        grant = user_payload.get("target_grant")
        missing = user_payload.get("missing_profile_fields") or []
        ledger = user_payload.get("facts_ledger") or []
        major = next((e["value"] for e in ledger if e["category"] == "major"), "Academic Field")
        grad_year = next((e["value"] for e in ledger if e["category"] == "expected_graduation_year"), None)

        grant_line = f"Target Grant: {grant['title']}" if grant else ""
        if doc_type == "recommendation_support":
            if lang == "en":
                draft = (
                    f"1. Polite Request Message:\nDear Professor, I am applying for {grant['title'] if grant else 'graduate scholarships'} "
                    f"in {major} and would be grateful for your academic recommendation.\n\n"
                    f"2. One-Page Recommender Brief:\n- Field: {major}\n- Graduation: {grad_year or 'Pending'}\n"
                    f"- Official criteria summary: {grant_line}\n\n"
                    "3. Structure Guidance:\nHighlight academic rigor, analytical teamwork, and readiness."
                )
            else:
                draft = (
                    f"1- رسالة طلب توصية مهذبة:\nأستاذي الفاضل، أتقدم بطلب للمنحة ({grant['title'] if grant else 'الدراسات العليا'}) في تخصص {major}، وأرجو تفضلكم بتزويدي برسالة توصية أكاديمية.\n\n"
                    f"2- ملخص للموصي (صفحة واحدة):\n- التخصص: {major}\n- سنة التخرج: {grad_year or 'غير مضافة بعد'}\n"
                    "3- إرشادات البنية:\nإبراز الأداء الأكاديمي والالتزام البحثي وفق معايير المنحة."
                )
        elif lang == "en":
            draft = (
                f"Motivation & Academic Summary in {major} {grant_line}.\n"
                f"Graduation year: {grad_year or 'Please add your graduation year'}.\n"
                "Prepared strictly from your verified profile notes."
            )
        else:
            draft = (
                f"مسودة أكاديمية منظمة في تخصص {major} {grant_line}.\n"
                f"سنة التخرج: {grad_year or 'يرجى إضافة سنة التخرج'}.\n"
                "صيغت هذه المسودة استناداً فقط إلى حقائقك المثبتة دون اختراع أي إنجاز أو جائزة."
            )

        return schema.model_validate(
            {
                "draft_text": draft,
                "sections": [{"title": "Summary", "content": draft}],
                "claims": [],
                "missing_info_requests": list(missing),
            }
        )


async def eval_documents(case_input: Dict[str, Any], *, live: Optional[bool] = None) -> Dict[str, Any]:
    """Evaluate document drafting + Facts Ledger anti-fabrication against isolated temp DB."""
    import tempfile
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import core.db as core_db
    from core.models import Grant, GrantStatus, StudentConsent, StudentSession
    from migrations.runner import run_migrations
    from modules.documents.schemas import DocumentGenerateRequest
    from modules.documents.service import DocumentsService
    from modules.students.schemas import CURRENT_CONSENT_VERSION, StudentProfileUpsertRequest
    from modules.students.service import StudentService
    from seed.seed_db import seed_database

    prev_engine = core_db.engine
    prev_session_local = core_db.SessionLocal

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "eval_docs.db"
        eval_engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        eval_session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=eval_engine,
            expire_on_commit=False,
        )
        core_db.engine = eval_engine
        core_db.SessionLocal = eval_session_local
        try:
            run_migrations(eval_engine)
            seed_database(publish_all=True)

            session_id = "eval-docs-student"
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with core_db.get_db() as db:
                db.add(
                    StudentSession(
                        id=session_id,
                        token_hash="eval-docs-hash",
                        created_at=now,
                        last_seen_at=now,
                        expires_at=now.replace(year=now.year + 1),
                    )
                )
                db.add(
                    StudentConsent(
                        session_id=session_id,
                        consent_version=CURRENT_CONSENT_VERSION,
                        scopes_json={"profile_storage": True, "ai_processing": True},
                        accepted_at=now,
                    )
                )
                grant_id = None
                if case_input.get("grant_title"):
                    g = (
                        db.query(Grant)
                        .filter(
                            Grant.status == GrantStatus.PUBLISHED,
                            Grant.title.contains(str(case_input["grant_title"])),
                        )
                        .first()
                    )
                    if g:
                        grant_id = g.id
                db.flush()

            StudentService().save_profile(
                session_id,
                StudentProfileUpsertRequest(**case_input["student"]),
            )
            req = DocumentGenerateRequest(
                grant_id=grant_id,
                doc_type=case_input["doc_type"],
                language=case_input.get("language", "ar"),
                source_text=case_input["source_text"],
            )

            api_key = (os.getenv("LLM_API_KEY") or settings.LLM_API_KEY or "").strip()
            use_live = bool(api_key) if live is None else live

            svc = DocumentsService()
            if use_live:
                async with httpx.AsyncClient(
                    base_url=settings.resolved_llm_base_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS, connect=5.0),
                ) as http:
                    client = _CapturingLiveLLMClient(
                        http=http,
                        models=settings.resolved_llm_models,
                        extra_body=settings.resolved_llm_extra_body,
                        default_max_tokens=settings.DOCUMENTS_MAX_TOKENS,
                        response_format_mode=settings.LLM_RESPONSE_FORMAT_MODE,
                        configured=True,
                    )
                    res = await svc.generate_draft(session_id=session_id, request=req, llm=client)
                    captured = client.captured_requests
            else:
                stub = _StubDocumentsLLMClient()
                res = await svc.generate_draft(session_id=session_id, request=req, llm=stub)  # type: ignore[arg-type]
                captured = stub.captured_requests

            out = res.model_dump()
            out["summary_ar"] = res.draft_text if res.language == "ar" else ""
            out["has_conflict"] = len(res.conflicts) > 0
            out["has_missing_request"] = len(res.missing_info_requests) > 0
            out["_captured_llm_input"] = captured
            return out
        finally:
            core_db.engine = prev_engine
            core_db.SessionLocal = prev_session_local
            eval_engine.dispose()


async def eval_external_search(
    case_input: Dict[str, Any],
    *,
    live: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run Capability #4 (ProfileExternalSearchService) strictly against recorded fixture web pages."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import core.db as core_db
    from migrations.runner import run_migrations
    from modules.search.schemas import ExternalSearchRunRequest
    from modules.search.service import ProfileExternalSearchService, SearchRunBudget
    from utils.url_guard import UnsafeURLError, validate_outbound_url
    from utils.url_validator import is_trusted_domain

    eval_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    eval_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=eval_engine,
        future=True,
    )
    prev_engine = core_db.engine
    prev_session_local = core_db.SessionLocal
    core_db.engine = eval_engine
    core_db.SessionLocal = eval_session_local
    try:
        run_migrations(eval_engine)

        recorded_results = list(case_input.get("search_results") or [])
        recorded_pages: Dict[str, Any] = dict(case_input.get("pages") or {})

        def fake_search(_query: str, max_results: int) -> list[dict[str, str]]:
            return recorded_results[:max_results]

        import ipaddress

        def fake_resolve(host: str, _port: int):
            if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
                return [ipaddress.ip_address("127.0.0.1")]
            return [ipaddress.ip_address("93.184.216.34")]

        def offline_validate(url: str, _title: Optional[str] = None) -> tuple[bool, list[str]]:
            try:
                validate_outbound_url(url, resolve_fn=fake_resolve)
            except UnsafeURLError as exc:
                return False, [str(exc)]
            ok, reason = is_trusted_domain(url)
            return ok, [reason]

        def fake_fetch(url: str):
            validate_outbound_url(url, resolve_fn=fake_resolve)
            entry = recorded_pages.get(url)
            if entry is None:
                raise RuntimeError("HTTP 404 Not Found")
            if isinstance(entry, dict) and entry.get("ssrf_redirect"):
                raise UnsafeURLError(f"Redirect target blocked: {entry['ssrf_redirect']}")
            if isinstance(entry, dict) and entry.get("http_error"):
                raise RuntimeError(str(entry["http_error"]))
            text = entry["text"] if isinstance(entry, dict) else str(entry)
            return text, []

        api_key = (os.getenv("LLM_API_KEY") or settings.LLM_API_KEY or "").strip()
        use_live = bool(api_key) if live is None else live

        req = ExternalSearchRunRequest(**case_input["request"])
        budget_cfg = case_input.get("budget")
        budget = SearchRunBudget(**budget_cfg) if budget_cfg else None
        svc = ProfileExternalSearchService(
            search_fn=fake_search,
            fetch_fn=fake_fetch,
            validate_fn=offline_validate,
        )

        if use_live:
            async with httpx.AsyncClient(
                base_url=settings.resolved_llm_base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS, connect=5.0),
            ) as http:
                client = AsyncLLMClient(
                    http=http,
                    models=settings.resolved_llm_models,
                    extra_body=settings.resolved_llm_extra_body,
                    default_max_tokens=settings.LLM_MAX_TOKENS,
                    response_format_mode=settings.LLM_RESPONSE_FORMAT_MODE,
                    configured=True,
                )
                res = await svc.run_search(request=req, llm=client, budget=budget)
        else:
            res = await svc.run_search(request=req, llm=None, budget=budget)

        out = res.model_dump()
        out["results_count"] = len(res.results)
        out["first_url"] = res.results[0].official_url if res.results else None
        out["first_eligibility"] = res.results[0].eligibility_verdict if res.results else None
        out["first_eligible"] = res.results[0].match_result.eligible if res.results else None
        out["rejected_targets"] = [s.target for s in res.step_log if s.verdict == "rejected"]
        out["rejected_blob"] = " | ".join(
            f"{s.target or ''}:{s.message_en}" for s in res.step_log if s.verdict in ("rejected", "stopped")
        )
        return out
    finally:
        core_db.engine = prev_engine
        core_db.SessionLocal = prev_session_local
        eval_engine.dispose()


