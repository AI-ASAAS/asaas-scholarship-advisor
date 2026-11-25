"""Phase 5 tests: profile strengthening, Facts Ledger anti-fabrication, documents API, retention, and privacy."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import core.db as core_db
from api.main import app
from core.config import settings
from core.db import get_db
from core.models import DocumentDraft, Grant, GrantStatus, YemeniEligibilityStatus
from migrations.runner import run_migrations
from modules.documents.ledger import (
    build_facts_ledger,
    normalize_digits_and_text,
    verify_draft_against_ledger,
)
from modules.documents.repository import DocumentsRepository
from modules.documents.service import compute_deterministic_gaps
from modules.llm.client import LLMError, get_llm
from modules.students.schemas import ConsentRecordRequest, StudentProfileUpsertRequest


@pytest.fixture()
def client():
    run_migrations(core_db.engine)
    with TestClient(app) as c:
        yield c


class _FakeStructuredLLM:
    """Fake AsyncLLMClient returning scripted JSON schema instances."""

    def __init__(self, payloads: List[Any], *, configured: bool = True) -> None:
        self._payloads = list(payloads)
        self._configured = configured
        self.calls: List[Dict[str, Any]] = []

    async def structured(self, messages, schema, *, prompt_version, **options):
        self.calls.append(
            {
                "messages": list(messages),
                "schema": schema.__name__,
                "prompt_version": prompt_version,
                "max_tokens": options.get("max_tokens"),
            }
        )
        if not self._payloads:
            raise AssertionError("FakeStructuredLLM ran out of responses")
        nxt = self._payloads.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return schema.model_validate(nxt)


def _setup_student_session(client: TestClient) -> None:
    c = client.post("/api/students/consent", json=ConsentRecordRequest().model_dump())
    assert c.status_code == 200
    p = client.put(
        "/api/students/profile",
        json=StudentProfileUpsertRequest(
            nationality="YE",
            country_of_residence="YE",
            current_degree="bachelor",
            target_degree="master",
            major="Computer Science",
            gpa_raw="3.2",
            gpa_scale="4.0",
            languages=[],
            target_countries=["DE", "GB"],
            funding_need="full",
            work_experience_years=1.5,
            experience_notes=["Built local school attendance app in Sanaa"],
            consent_accepted=True,
        ).model_dump(),
    )
    assert p.status_code == 200


# ---------------------------------------------------------------------------
# Facts Ledger Unit Tests (True positives & False negative prevention)
# ---------------------------------------------------------------------------


def test_ledger_normalizes_arabic_indic_digits_and_transliterated_names():
    profile = {
        "nationality": "YE",
        "current_degree": "bachelor",
        "target_degree": "master",
        "major": "علوم الحاسوب",
        "gpa_raw": "3.65",
        "gpa_scale": "4.0",
        "gpa_normalized_4": 3.65,
        "expected_graduation_year": 2024,
        "languages": [{"language": "English", "test_name": "IELTS", "score": 7.0}],
        "experience_notes": ["جامعة صنعاء - مشروع تخرج في النظم الذكية"],
    }
    ledger, conflicts, missing = build_facts_ledger(
        profile=profile,
        source_text="I graduated in ٢٠٢٤ from Sana'a University in Computer Science with IELTS ٧.٠.",
    )
    assert conflicts == []
    assert missing == []

    # Valid draft translating جامعة صنعاء -> Sanaa University and using Arabic-Indic/Latin equivalents
    clean_draft = (
        "I completed my Bachelor degree in Computer Science at Sanaa University in 2024 "
        "with a GPA of ٣.٦٥ and IELTS 7.0."
    )
    flags = verify_draft_against_ledger(draft_text=clean_draft, doc_type="cv", ledger=ledger)
    assert flags == [], f"Unexpected false positives: {flags}"


def test_ledger_catches_fabricated_award_number_date_employer_and_conflict():
    profile = {
        "nationality": "YE",
        "current_degree": "bachelor",
        "target_degree": "master",
        "major": "Public Policy",
        "gpa_raw": "3.2",
        "gpa_scale": "4.0",
        "gpa_normalized_4": 3.2,
        "languages": [],
        "experience_notes": [],
    }
    pasted = "عملت متطوعاً في جمعية تعليمية وحصلت على معدل 3.9 من 4.0."
    ledger, conflicts, missing = build_facts_ledger(profile=profile, source_text=pasted)

    # GPA conflict caught deterministically + missing graduation year / language requested
    assert len(conflicts) == 1
    assert conflicts[0].category == "conflict"
    assert any("التخرج" in m for m in missing)

    fabricated_draft = (
        "Graduated from Oxford University in 2021 and worked at Acme Global Corp. "
        "Winner of Nobel Peace Prize and scored 98% overall."
    )
    flags = verify_draft_against_ledger(
        draft_text=fabricated_draft,
        doc_type="motivation_letter",
        ledger=ledger,
        existing_conflicts=conflicts,
    )
    flagged_blobs = " | ".join(f.claim_text.lower() for f in flags)
    assert "oxford university" in flagged_blobs
    assert "2021" in flagged_blobs
    assert "acme global corp" in flagged_blobs
    assert "nobel" in flagged_blobs
    assert "98" in flagged_blobs


def test_ledger_catches_recommender_voice_violation():
    ledger, _, _ = build_facts_ledger(
        profile={"nationality": "YE", "major": "Physics"},
        source_text="Research assistant on solar panels.",
    )
    bad_rec = (
        "To whom it may concern, I strongly recommend the applicant for admission. "
        "As his professor, I certify he is in the top 5%."
    )
    flags = verify_draft_against_ledger(
        draft_text=bad_rec,
        doc_type="recommendation_support",
        ledger=ledger,
    )
    cats = {f.category for f in flags}
    assert "recommendation_voice" in cats
    assert "number" in cats  # invented 5%


def test_compute_deterministic_gaps_flags_tight_language_deadline_as_assumption():
    profile = {
        "nationality": "YE",
        "target_degree": "master",
        "major": "Engineering",
        "gpa_raw": "2.6",
        "gpa_scale": "4.0",
        "gpa_normalized_4": 2.6,
        "languages": [],
    }
    grants = [
        {
            "id": 101,
            "title": "Close Deadline Grant",
            "official_url": "https://example.edu/close",
            "deadline": date(2026, 6, 20),  # 19 days after reference date (< 6 weeks assumption)
            "accepts_yemeni": "yes",
            "nationality_rule": {"mode": "all", "countries": [], "groups": []},
            "allowed_degrees": ["master"],
            "min_gpa_value": 3.0,
            "min_gpa_scale": "4.0",
            "min_gpa_normalized_4": 3.0,
            "language_requirements": [{"language": "English", "test": "IELTS", "min_score": 6.5}],
            "required_documents": ["CV", "Motivation Letter", "Transcripts"],
            "evidence": {
                "language_requirements": "IELTS 6.5 minimum",
                "min_gpa": "Minimum GPA 3.0/4.0",
            },
        }
    ]
    gaps = compute_deterministic_gaps(
        profile, grants, reference_date=date(2026, 6, 1), assumed_test_weeks=6
    )
    gap_types = {g.gap_type for g in gaps}
    assert "language" in gap_types
    assert "deadline_proximity" in gap_types
    assert "gpa" in gap_types
    tight = next(g for g in gaps if g.gap_type == "deadline_proximity")
    assert tight.is_assumption is True


# ---------------------------------------------------------------------------
# HTTP Integration, Auth, Isolation, Limits & Deletion Tests
# ---------------------------------------------------------------------------


def test_strengthening_and_generate_enforce_limits_isolation_and_delete(client: TestClient):
    # Unauthenticated -> 401
    assert client.get("/api/documents").status_code == 401

    _setup_student_session(client)

    # 1. Oversized pasted text (> 8000 chars) -> 422
    too_big = "أ" * (settings.DOCUMENTS_MAX_INPUT_CHARS + 1)
    r_422 = client.post(
        "/api/documents/generate",
        json={"doc_type": "cv", "language": "ar", "source_text": too_big},
    )
    assert r_422.status_code == 422

    # 2. LLM outage -> 503 retryable
    app.dependency_overrides[get_llm] = lambda: _FakeStructuredLLM([LLMError("outage")], configured=True)
    try:
        r_503 = client.post(
            "/api/documents/generate",
            json={"doc_type": "cv", "language": "ar", "source_text": "عملت مطور برمجيات لمدة عام في صنعاء."},
        )
        assert r_503.status_code == 503
        assert r_503.json()["code"] == "LLM_UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()

    # 3. Successful generation returns flagged invented claims AND does not save automatically
    fake_gen = _FakeStructuredLLM(
        [
            {
                "draft_text": "سيرة ذاتية: خريج جامعة صنعاء في Computer Science بمعدل 3.2 وحاصل على Nobel Prize 2021.",
                "sections": [{"title": "التعليم", "content": "علوم الحاسوب"}],
                "claims": [{"text": "جامعة صنعاء", "category": "institution", "ledger_id": "L1"}],
                "missing_info_requests": ["أضف سنة التخرج"],
            }
        ],
        configured=True,
    )
    app.dependency_overrides[get_llm] = lambda: fake_gen
    try:
        gen_resp = client.post(
            "/api/documents/generate",
            json={
                "doc_type": "cv",
                "language": "ar",
                "source_text": "تخرجت من جامعة صنعاء تخصص Computer Science، عملت في تطبيق مدرسة.",
            },
        )
        assert gen_resp.status_code == 200
        body = gen_resp.json()
        assert body["prompt_version"] == "documents@1.0"
        assert "Nobel" in " ".join(c["claim_text"] for c in body["flagged_claims"])
        assert "2021" in " ".join(c["claim_text"] for c in body["flagged_claims"])
        # Generation must NOT persist automatically until student saves
        assert client.get("/api/documents").json()["count"] == 0
    finally:
        app.dependency_overrides.clear()

    # 4. Save draft explicitly -> export .txt -> another student cannot read/edit/delete
    save_resp = client.post(
        "/api/documents",
        json={
            "doc_type": "cv",
            "language": "ar",
            "draft_text": body["draft_text"],
            "facts_ledger": body["facts_ledger"],
            "flagged_claims": body["flagged_claims"],
            "prompt_version": body["prompt_version"],
        },
    )
    assert save_resp.status_code == 201
    draft_id = save_resp.json()["id"]

    exp = client.get(f"/api/documents/{draft_id}/export")
    assert exp.status_code == 200
    assert "text/plain" in exp.headers["content-type"]
    assert f'filename="asaas-document-{draft_id}.txt"' in exp.headers["content-disposition"]

    # Another student session cannot access draft_id
    with TestClient(app) as student_b:
        _setup_student_session(student_b)
        assert student_b.get("/api/documents").json()["count"] == 0
        assert student_b.get(f"/api/documents/{draft_id}/export").status_code == 404
        assert (
            student_b.patch(
                f"/api/documents/{draft_id}",
                json={"draft_text": "unauthorized modification attempt"},
            ).status_code
            == 404
        )
        assert student_b.delete(f"/api/documents/{draft_id}").status_code == 404

    # 5. Purge retention check + atomic delete-my-data wipes document_drafts
    with get_db() as db:
        old_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=95)
        old_row = DocumentDraft(
            session_id=db.query(DocumentDraft).first().session_id,
            doc_type="cv",
            language="ar",
            facts_ledger_json=[],
            draft_text="old draft text",
            flagged_claims_json=[],
            created_at=old_dt,
            updated_at=old_dt,
        )
        db.add(old_row)
        db.flush()
        assert DocumentsRepository.purge_expired_drafts(db, 90) == 1

    del_all = client.delete("/api/students/data")
    assert del_all.status_code == 200
    assert del_all.json()["removed_counts"]["document_drafts"] == 1
    with get_db() as db:
        assert db.query(DocumentDraft).count() == 0


def test_strengthening_endpoint_references_real_gaps_and_respects_rate_limit(
    client: TestClient, monkeypatch
):
    from modules.documents.router import documents_rate_limiter

    _setup_student_session(client)

    # 1. Configured LLM returning 1 valid gap_id (G1) and 1 hallucinated gap_id (G999)
    fake_llm = _FakeStructuredLLM(
        [
            {
                "summary_ar": "خطة تقوية أولية مبنية على شروط المنح.",
                "actions": [
                    {
                        "gap_id": "G1",
                        "what_ar": "الحصول على شهادة IELTS",
                        "why_ar": "مطلوبة في Chevening وغيرها",
                        "next_step_ar": "احجز موعد الاختبار الرسمي",
                    },
                    {
                        "gap_id": "G999",
                        "what_ar": "معلومة مخترعة",
                        "why_ar": "لا وجود لها",
                        "next_step_ar": "تجاهل",
                    },
                ],
            }
        ],
        configured=True,
    )
    app.dependency_overrides[get_llm] = lambda: fake_llm
    try:
        res = client.post("/api/documents/strengthening", json={})
        assert res.status_code == 200
        body = res.json()
        assert body["used_fallback"] is False
        assert len(body["gaps"]) >= 1
        assert all(a["gap_id"] != "G999" for a in body["actions"])
        assert body["actions"][0]["gap_id"] == "G1"
    finally:
        app.dependency_overrides.clear()

    # Rate limit check -> 429 with Retry-After
    monkeypatch.setattr(settings, "DOCUMENTS_RATE_LIMIT_PER_HOUR", 1)
    documents_rate_limiter.reset()
    fake_rate = _FakeStructuredLLM(
        [
            {"draft_text": "سيرة ذاتية: خريج علوم الحاسوب ومطور في صنعاء.", "sections": [], "claims": [], "missing_info_requests": []},
        ],
        configured=True,
    )
    app.dependency_overrides[get_llm] = lambda: fake_rate
    try:
        r1 = client.post(
            "/api/documents/generate",
            json={"doc_type": "cv", "language": "ar", "source_text": "خريج علوم الحاسوب ومطور في صنعاء."},
        )
        assert r1.status_code == 200
        r2 = client.post(
            "/api/documents/generate",
            json={"doc_type": "cv", "language": "ar", "source_text": "خريج علوم الحاسوب ومطور في صنعاء."},
        )
        assert r2.status_code == 429
        assert "Retry-After" in r2.headers
    finally:
        app.dependency_overrides.clear()


def test_extract_file_endpoint_and_document_aware_strengthening(client: TestClient):
    """Verify file extraction (.txt/.docx/.pdf), security rejections, and document-aware strengthening."""
    import base64
    import io
    import zipfile
    from modules.documents.router import documents_rate_limiter

    documents_rate_limiter.reset()
    # Unauthenticated -> 401
    assert (
        client.post(
            "/api/documents/extract-file",
            json={"doc_type": "cv", "filename": "cv.txt", "content_base64": "aGVsbG8="},
        ).status_code
        == 401
    )

    _setup_student_session(client)

    # Disallowed extension -> 422
    bad_ext = client.post(
        "/api/documents/extract-file",
        json={"doc_type": "cv", "filename": "malware.exe", "content_base64": "TVqQAAMAAAA="},
    )
    assert bad_ext.status_code == 422

    # Legitimate .txt upload -> extracted text
    txt_raw = "Bachelor in Computer Science from Sanaa University with 2 years software experience."
    txt_b64 = base64.b64encode(txt_raw.encode("utf-8")).decode("ascii")
    r_txt = client.post(
        "/api/documents/extract-file",
        json={"doc_type": "cv", "filename": "my_cv.txt", "content_base64": txt_b64},
    )
    assert r_txt.status_code == 200
    assert "Sanaa University" in r_txt.json()["extracted_text"]

    # Legitimate .docx upload -> extracted text
    docx_buf = io.BytesIO()
    with zipfile.ZipFile(docx_buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Built community solar tracker in Aden.</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    docx_b64 = base64.b64encode(docx_buf.getvalue()).decode("ascii")
    r_docx = client.post(
        "/api/documents/extract-file",
        json={"doc_type": "motivation_letter", "filename": "letter.docx", "content_base64": docx_b64},
    )
    assert r_docx.status_code == 200
    assert "community solar tracker in Aden" in r_docx.json()["extracted_text"]

    # XXE / DOCTYPE inside .docx -> rejected cleanly with 422
    xxe_buf = io.BytesIO()
    with zipfile.ZipFile(xxe_buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            "<w:document><w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>",
        )
    r_xxe = client.post(
        "/api/documents/extract-file",
        json={
            "doc_type": "cv",
            "filename": "xxe.docx",
            "content_base64": base64.b64encode(xxe_buf.getvalue()).decode("ascii"),
        },
    )
    assert r_xxe.status_code == 422

    # Document-aware strengthening forwards uploaded docs (PII-scrubbed) and includes G_DOC_CV
    fake_llm = _FakeStructuredLLM(
        [
            {
                "summary_ar": "خطة مبنية على ملفك وسيرتك الذاتية المرفوعة.",
                "actions": [
                    {
                        "gap_id": "G_DOC_CV",
                        "what_ar": "إبراز خبرة البرمجيات وتوثيق سنوات الخبرة بوضوح",
                        "why_ar": "ورد في سيرتك الذاتية المرفوعة my_cv.txt دون تحديد المدة بالأرقام.",
                        "next_step_ar": "أضف التواريخ الدقيقة لمسؤولياتك في ملف السيرة الذاتية.",
                    }
                ],
            }
        ],
        configured=True,
    )
    app.dependency_overrides[get_llm] = lambda: fake_llm
    try:
        r_str = client.post(
            "/api/documents/strengthening",
            json={
                "documents": [
                    {
                        "doc_type": "cv",
                        "filename": "my_cv.txt",
                        "content": f"{txt_raw} Contact me at leak@example.com or +967777123456.",
                    },
                    {
                        "doc_type": "certificates",
                        "filename": "ielts_cert.txt",
                        "content": "IELTS Academic Certificate overall band 7.0 issued 2025.",
                    },
                ]
            },
        )
        assert r_str.status_code == 200
        body = r_str.json()
        assert any(g["gap_id"] == "G_DOC_CV" for g in body["gaps"])
        assert any(g["gap_id"] == "G_DOC_CERTIFICATES" for g in body["gaps"])
        assert any(a["gap_id"] == "G_DOC_CV" for a in body["actions"])
        sent_user_msg = fake_llm.calls[0]["messages"][1]["content"]
        assert "Sanaa University" in sent_user_msg
        assert "leak@example.com" not in sent_user_msg
    finally:
        app.dependency_overrides.clear()
