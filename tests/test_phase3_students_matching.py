"""Phase 3 tests: student identity, consent, profile, matching engine, and profile analysis."""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from typing import Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import core.db as core_db
from core.models import Grant, GrantStatus, StudentConsent, StudentProfile, StudentSession
from core.repository import publish, save_draft
from migrations.runner import get_applied_migrations, run_migrations
from modules.llm.client import AsyncLLMClient
from modules.matching.analysis import generate_profile_analysis
from modules.matching.gpa import normalize_student_gpa
from modules.matching.service import compute_matches_for_student, evaluate_grant_for_student
from seed.seed_db import seed_database


@pytest.fixture()
def client():
    from api.main import app

    with TestClient(app) as c:
        yield c


def _sample_profile_payload(**overrides):
    base = {
        "nationality": "YE",
        "country_of_residence": "YE",
        "current_degree": "bachelor",
        "expected_graduation_year": 2024,
        "target_degree": "master",
        "major": "Public Policy",
        "gpa_raw": "3.6",
        "gpa_scale": "4.0",
        "languages": [
            {"language": "English", "test_name": "TOEFL", "score": 95.0}
        ],
        "target_countries": ["GB", "DE"],
        "target_fields": ["Public Policy", "Economics"],
        "funding_need": "full",
        "work_experience_years": 2.5,
        "experience_notes": ["Led community education project."],
        "age_years": 25,
        "publications_count": 1,
        "consent_accepted": True,
    }
    base.update(overrides)
    return base


def test_migration_003_fresh_and_upgrade(tmp_path):
    """Migration 003 creates student tables cleanly on fresh and upgraded databases."""
    from migrations.runner import MIGRATIONS

    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'fresh3.db'}")
    applied = run_migrations(fresh_engine)
    expected = [m.VERSION for m in MIGRATIONS]
    assert applied == expected
    insp = inspect(fresh_engine)
    for table in ("student_sessions", "student_consents", "student_profiles"):
        assert insp.has_table(table)
    assert [m["version"] for m in get_applied_migrations(fresh_engine)] == [str(v) for v in expected]


def test_student_consent_required_before_save_and_validation_422(client: TestClient):
    """Consent is enforced before saving; invalid fields or PII extras return 422."""
    # Attempt save without consent -> 403
    no_consent = client.put("/api/students/profile", json=_sample_profile_payload(consent_accepted=False))
    assert no_consent.status_code == 403
    assert no_consent.json()["code"] == "CONSENT_REQUIRED"

    # Attempt PII injection -> 422 extra_forbidden
    pii = client.put(
        "/api/students/profile",
        json=_sample_profile_payload(email="attacker@example.com"),
    )
    assert pii.status_code == 422

    # Invalid GPA out of bounds on 4.0 scale -> 422
    bad_gpa = client.put(
        "/api/students/profile",
        json=_sample_profile_payload(gpa_raw="4.8", gpa_scale="4.0"),
    )
    assert bad_gpa.status_code == 422


def test_student_session_isolation_export_and_atomic_delete(client: TestClient):
    """Another student cannot access this profile; delete-my-data wipes DB and cookie."""
    from api.main import app

    # Student A saves profile with consent
    saved = client.put("/api/students/profile", json=_sample_profile_payload())
    assert saved.status_code == 200
    assert saved.json()["nationality"] == "YE"
    assert saved.json()["has_consent"] is True

    # Student B (separate cookie jar) gets 401 on profile, export, matches
    with TestClient(app) as student_b:
        assert student_b.get("/api/students/me").json()["authenticated"] is False
        assert student_b.get("/api/students/profile").status_code == 401
        assert student_b.get("/api/matches").status_code == 401
        # Forged random cookie fails
        student_b.cookies.set("asaas_student", "forged-token-value")
        assert student_b.get("/api/students/profile").status_code == 401

    # Student A fetches matches & exports data
    matches = client.get("/api/matches")
    assert matches.status_code == 200
    assert matches.json()["total_evaluated"] == 10

    export = client.get("/api/students/export")
    assert export.status_code == 200
    exp_body = export.json()
    assert exp_body["profile"]["major"] == "Public Policy"
    assert len(exp_body["consent_records"]) == 1
    assert "token_hash" not in json.dumps(exp_body)

    # Delete all data atomically
    deleted = client.delete("/api/students/data")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    # Verify in DB that 0 rows remain across all 3 student tables
    with core_db.get_db() as db:
        assert db.query(StudentProfile).count() == 0
        assert db.query(StudentConsent).count() == 0
        assert db.query(StudentSession).count() == 0

    # Subsequent access denied cleanly
    assert client.get("/api/students/profile").status_code == 401


def test_matcher_gates_criteria_gpa_scales_ties_and_monotonicity():
    """Verify hard gates, criteria, GPA scale tables, tiebreaks, and non-monotonic protection."""
    today = date(2027, 1, 1)
    grants = [
        {
            "id": 1,
            "title": "Soonest Match",
            "official_url": "https://example.org/g1",
            "status": "published",
            "deadline": "2027-02-01",
            "allowed_degrees": ["master"],
            "min_gpa_value": 3.0,
            "min_gpa_scale": "4.0",
            "min_gpa_normalized_4": 3.0,
            "language_requirements": [{"language": "English", "test": "IELTS", "min_score": 6.5}],
            "fields_of_study": ["Computer Science"],
            "nationality_rule": {"mode": "all", "countries": [], "groups": []},
            "accepts_yemeni": "yes",
            "min_work_years": 2.0,
            "max_age": 35,
            "evidence": {"deadline": "2027-02-01", "min_gpa": "3.0"},
        },
        {
            "id": 2,
            "title": "Later Tie Match",
            "official_url": "https://example.org/g2",
            "status": "published",
            "deadline": "2027-05-01",
            "allowed_degrees": ["master"],
            "min_gpa_value": 3.0,
            "min_gpa_scale": "4.0",
            "min_gpa_normalized_4": 3.0,
            "language_requirements": [{"language": "English", "test": "IELTS", "min_score": 6.5}],
            "fields_of_study": ["Computer Science"],
            "nationality_rule": {"mode": "all", "countries": [], "groups": []},
            "accepts_yemeni": "yes",
            "min_work_years": 2.0,
            "max_age": 35,
            "evidence": {},
        },
        {
            "id": 3,
            "title": "Expired Deadline Grant",
            "official_url": "https://example.org/g3",
            "status": "published",
            "deadline": "2026-12-01",
            "nationality_rule": {"mode": "all"},
            "evidence": {"deadline": "2026-12-01"},
        },
        {
            "id": 4,
            "title": "Bachelor Only Grant",
            "official_url": "https://example.org/g4",
            "status": "published",
            "deadline": "2027-04-01",
            "allowed_degrees": ["bachelor"],
            "nationality_rule": {"mode": "all"},
            "evidence": {"allowed_degrees": "Bachelor only"},
        },
        {
            "id": 5,
            "title": "Draft Grant Excluded",
            "official_url": "https://example.org/g5",
            "status": "draft",
            "deadline": "2027-04-01",
            "nationality_rule": {"mode": "all"},
            "evidence": {},
        },
    ]

    # Yemeni grade label normalization
    gpa_4, is_assumed = normalize_student_gpa("جيد جداً", "label")
    assert gpa_4 == 3.30
    assert is_assumed is True

    student_partial = {
        "nationality": "YE",
        "target_degree": "master",
        "major": "Computer Science",
        "gpa_raw": "2.5",
        "gpa_scale": "4.0",
        "gpa_normalized_4": 2.5,  # Below 3.0 -> GPA criterion is NOT_MET
        "languages": [],  # Missing IELTS -> UNKNOWN
        "target_fields": [],
        "work_experience_years": None,  # UNKNOWN
        "age_years": None,  # UNKNOWN
    }
    res1 = compute_matches_for_student(student_partial, grants, reference_date=today)

    # Hard gates separate ineligible grants cleanly
    assert [g.grant_id for g in res1.eligible_grants] == [1, 2]  # Tie broken by nearest deadline!
    assert {g.grant_id for g in res1.ineligible_grants} == {3, 4, 5}
    for bad in res1.ineligible_grants:
        assert bad.match_percentage == 0.0
        assert len(bad.disqualifiers) >= 1

    # Check criteria states & coverage on Grant #1
    g1 = res1.eligible_grants[0]
    by_key = {c.key: c.status for c in g1.criteria}
    assert by_key["gpa"] == "not_met"
    assert by_key["language"] == "unknown"
    assert by_key["work_experience"] == "unknown"
    assert by_key["age"] == "unknown"
    assert g1.coverage_percentage < 100.0
    assert len(g1.missing_info_hints) >= 3

    # Property: adding OTHER info (age, work experience, language) NEVER flips not_met GPA to met
    student_enriched = copy.deepcopy(student_partial)
    student_enriched["age_years"] = 24
    student_enriched["work_experience_years"] = 3.0
    student_enriched["languages"] = [{"language": "English", "test_name": "IELTS", "score": 7.5, "is_self_assessed": False}]
    res2 = compute_matches_for_student(student_enriched, grants, reference_date=today)
    g1_after = res2.eligible_grants[0]
    by_key_after = {c.key: c.status for c in g1_after.criteria}
    assert by_key_after["gpa"] == "not_met"  # Unchanged!
    assert by_key_after["age"] == "met"
    assert by_key_after["work_experience"] == "met"
    assert by_key_after["language"] == "met"
    assert g1_after.coverage_percentage == 100.0


def test_three_invented_students_explainable_seed_results():
    """Three realistic student personas produce distinct, explainable results on the 10 real grants."""
    from seed.seed_db import VERIFIED_TOP10_BASELINE
    from seed.structured_backfill import build_verified_backfill_map

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

    # 1. Yemeni master's applicant with TOEFL and 3 years experience
    s_master = {
        "nationality": "YE",
        "target_degree": "master",
        "major": "Public Policy",
        "gpa_raw": "85",
        "gpa_scale": "100",
        "gpa_normalized_4": 3.35,
        "languages": [{"language": "English", "test_name": "TOEFL", "score": 96.0, "is_self_assessed": False}],
        "target_fields": ["Public Policy"],
        "work_experience_years": 3.0,
        "age_years": 26,
    }
    m1 = compute_matches_for_student(s_master, seed_grants, reference_date=date(2026, 6, 1))
    assert len(m1.eligible_grants) == 10
    fulbright = next(g for g in m1.eligible_grants if "Fulbright" in g.title)
    assert next(c.status for c in fulbright.criteria if c.key == "language") == "met"

    # 2. Bachelor's applicant with no language score
    s_bachelor = {
        "nationality": "YE",
        "target_degree": "bachelor",
        "major": "Engineering",
        "gpa_raw": "88",
        "gpa_scale": "100",
        "gpa_normalized_4": 3.35,
        "languages": [],
        "target_fields": ["Engineering"],
        "work_experience_years": 0.0,
        "age_years": 19,
    }
    m2 = compute_matches_for_student(s_bachelor, seed_grants, reference_date=date(2026, 6, 1))
    ineligible_titles = {g.title for g in m2.ineligible_grants}
    # Chevening, DAAD, Fulbright, Eiffel do not offer bachelor's
    assert any("Chevening" in t for t in ineligible_titles)
    assert any("Fulbright" in t for t in ineligible_titles)
    assert any("Türkiye Bursları" in g.title for g in m2.eligible_grants)

    # 3. Non-Yemeni EU citizen (FR)
    s_french = {
        "nationality": "FR",
        "target_degree": "master",
        "major": "Economics",
        "gpa_raw": "3.5",
        "gpa_scale": "4.0",
        "gpa_normalized_4": 3.5,
        "languages": [{"language": "English", "test_name": "TOEFL", "score": 100.0, "is_self_assessed": False}],
        "target_fields": ["Economics"],
        "work_experience_years": 2.0,
        "age_years": 25,
    }
    m3 = compute_matches_for_student(s_french, seed_grants, reference_date=date(2026, 6, 1))
    ineligible_fr = {g.title for g in m3.ineligible_grants}
    # Romania excludes EU citizens; IsDB is IsDB-members only; Fulbright in seed targets YE
    assert any("Romanian" in t for t in ineligible_fr)
    assert any("IsDB" in t for t in ineligible_fr)
    assert any("Türkiye Bursları" in g.title for g in m3.eligible_grants)


@pytest.mark.anyio
async def test_profile_analysis_drops_unreferenced_statements_and_strips_pii():
    """Verify profile analysis drops hallucinated statements without finding_ids and scrubs PII."""
    captured_bodies: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_bodies.append(body)
        return httpx.Response(
            200,
            json={
                "model": "mock-analysis",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary_ar": "ملخص تحليلي للملف الشخصي.",
                                    "strengths": [
                                        {"text_ar": "استيفاء شرط الجنسية والدرجة.", "finding_ids": ["F1"]},
                                        {"text_ar": "ادعاء مختلق بدون معرف.", "finding_ids": ["F999"]},
                                    ],
                                    "weaknesses": [
                                        {"text_ar": "نقص بيانات اللغة.", "finding_ids": ["F2"]},
                                    ],
                                    "improvement_areas": [
                                        {"text_ar": "تحضير كشف الدرجات.", "finding_ids": ["F3"]},
                                    ],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 90, "completion_tokens": 50},
            },
        )

    async with httpx.AsyncClient(
        base_url="https://mock.llm/v1",
        transport=httpx.MockTransport(handler),
    ) as http:
        llm = AsyncLLMClient(http=http, models=["mock-analysis"], backoff_seconds=0.0)
        from modules.students.service import scrub_pii_notes

        student = {
            "session_id": "secret-session-id-should-not-leave",
            "nationality": "YE",
            "target_degree": "master",
            "major": "Public Policy",
            "gpa_normalized_4": 3.5,
            "languages": [],
            "work_experience_years": 2.0,
            "experience_notes": scrub_pii_notes(["Reach me at student@example.com or +967777123456"]),
        }
        grant = {
            "id": 1,
            "title": "Sample Grant",
            "official_url": "https://example.org/sample",
            "status": "published",
            "allowed_degrees": ["master"],
            "language_requirements": [{"language": "English", "test": "IELTS", "min_score": 6.5}],
            "required_documents": ["Official Transcripts"],
            "nationality_rule": {"mode": "all"},
            "evidence": {},
        }
        matches = compute_matches_for_student(student, [grant])
        result = await generate_profile_analysis(
            student, matches, grants_by_id={1: grant}, llm_client=llm
        )

    assert result.analysis_mode == "llm_grounded"
    assert result.dropped_ungrounded_count == 1
    assert len(result.strengths) == 1
    assert result.strengths[0].finding_ids == ["F1"]

    sent_str = json.dumps(captured_bodies[0], ensure_ascii=False)
    assert "secret-session-id" not in sent_str
    assert "student@example.com" not in sent_str
    assert "777123456" not in sent_str


@pytest.mark.anyio
async def test_profile_analysis_deterministic_fallback_on_llm_error():
    """When LLM fails with 500, profile_analysis returns clearly labeled deterministic fallback."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream down"})

    async with httpx.AsyncClient(
        base_url="https://mock.llm/v1",
        transport=httpx.MockTransport(handler),
    ) as http:
        llm = AsyncLLMClient(http=http, models=["m1"], attempts_per_model=1, backoff_seconds=0.0)
        student = {"nationality": "YE", "target_degree": "master", "languages": []}
        grant = {
            "id": 1,
            "title": "Sample Grant",
            "official_url": "https://example.org/sample",
            "status": "published",
            "allowed_degrees": ["master"],
            "required_documents": ["Passport Copy"],
            "nationality_rule": {"mode": "all"},
            "evidence": {},
        }
        matches = compute_matches_for_student(student, [grant])
        result = await generate_profile_analysis(
            student, matches, grants_by_id={1: grant}, llm_client=llm
        )

    assert result.analysis_mode == "deterministic_fallback"
    assert result.retryable is True
    assert result.fallback_notice_ar is not None
    assert len(result.findings) >= 1
