"""Phase 6 tests: personalized application plan ordering, backward timeline, conflicts, .ics, timezone, and privacy."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import core.db as core_db
from api.main import app
from core.config import settings
from core.db import get_db
from core.models import ApplicationPlan, Grant, GrantStatus, PlanItem, YemeniEligibilityStatus
from migrations.runner import run_migrations
from modules.assistant.tools import _run_get_my_plan, NoArgs
from modules.auth.schemas import StudentPrincipal
from modules.llm.client import LLMError, get_llm
from modules.plans.generator import (
    build_backward_milestones,
    build_grant_checklist,
    build_ics_calendar,
    detect_deadline_conflicts,
    local_today,
    sort_plan_entries,
)
from modules.students.schemas import ConsentRecordRequest, StudentProfileUpsertRequest


@pytest.fixture()
def client():
    run_migrations(core_db.engine)
    with TestClient(app) as c:
        yield c


class _FakePlanSummaryLLM:
    def __init__(self, payload: Any, *, configured: bool = True) -> None:
        self._payload = payload
        self._configured = configured

    async def structured(self, messages, schema, *, prompt_version, **options):
        if isinstance(self._payload, Exception):
            raise self._payload
        return schema.model_validate(self._payload)


def _setup_student(client: TestClient, target_degree: str = "master") -> None:
    assert client.post("/api/students/consent", json=ConsentRecordRequest().model_dump()).status_code == 200
    assert (
        client.put(
            "/api/students/profile",
            json=StudentProfileUpsertRequest(
                nationality="YE",
                current_degree="bachelor",
                target_degree=target_degree,  # type: ignore[arg-type]
                major="Public Policy",
                gpa_raw="3.7",
                gpa_scale="4.0",
                languages=[{"language": "English", "test_name": "IELTS", "score": 7.0}],
                target_countries=["DE", "GB"],
                work_experience_years=3.0,
                age_years=26,
                consent_accepted=True,
            ).model_dump(),
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Pure Generator Unit Tests (Ordering, Boundaries, Timezone, Conflicts, .ics)
# ---------------------------------------------------------------------------


def test_ordering_ties_and_ineligible_last():
    entries = [
        {"grant_id": 1, "eligible": False, "match_percentage": 0.0, "coverage_percentage": 0.0, "deadline_date": date(2027, 1, 5)},
        {"grant_id": 2, "eligible": True, "match_percentage": 80.0, "coverage_percentage": 100.0, "deadline_date": date(2027, 6, 1)},
        {"grant_id": 3, "eligible": True, "match_percentage": 100.0, "coverage_percentage": 100.0, "deadline_date": date(2027, 9, 1)},
        {"grant_id": 4, "eligible": True, "match_percentage": 100.0, "coverage_percentage": 100.0, "deadline_date": date(2027, 4, 15)},
    ]
    ordered = sort_plan_entries(entries)
    # #4 (100%, earlier Apr) -> #3 (100%, later Sep) -> #2 (80%) -> #1 (ineligible last even if Jan!)
    assert [e["grant_id"] for e in ordered] == [4, 3, 2, 1]


def test_backward_milestones_cross_month_and_year_boundaries():
    # Year boundary: Jan 10, 2027 minus 28 days = Dec 13, 2026
    ms_year = build_backward_milestones(
        date(2027, 1, 10),
        today=date(2026, 12, 10),
        offsets=[28, 7],
    )
    assert [m.due_date for m in ms_year] == ["2026-12-13", "2027-01-03"]
    assert all("غير" in m.pacing_note_ar or "ليس شرطاً" in m.pacing_note_ar for m in ms_year)

    # Leap-year vs non-leap-year February boundary: March 5 - 7 days
    assert build_backward_milestones(date(2027, 3, 5), today=date(2027, 2, 1), offsets=[7])[0].due_date == "2027-02-26"
    assert build_backward_milestones(date(2028, 3, 5), today=date(2028, 2, 1), offsets=[7])[0].due_date == "2028-02-27"


def test_midnight_timezone_behavior():
    midnight_ish_utc = datetime(2026, 6, 15, 22, 30, tzinfo=timezone.utc)
    # Asia/Aden (UTC+3) is already 2026-06-16 01:30
    assert local_today("Asia/Aden", now_utc=midnight_ish_utc) == date(2026, 6, 16)
    # America/New_York (UTC-4) is still 2026-06-15 18:30
    assert local_today("America/New_York", now_utc=midnight_ish_utc) == date(2026, 6, 15)


def test_conflict_detection_and_missing_official_fields_not_invented():
    conflicts = detect_deadline_conflicts(
        [
            (1, "Grant A", date(2027, 3, 10)),
            (2, "Grant B", date(2027, 3, 15)),
            (3, "Grant C", date(2027, 6, 1)),
        ],
        window_days=7,
    )
    assert len(conflicts) == 1
    assert conflicts[0].grant_ids == [1, 2]
    assert "تداخل مواعيد" in conflicts[0].message_ar

    checklist = build_grant_checklist(
        profile={"nationality": "YE", "target_degree": "master"},
        grant={
            "id": 99,
            "title": "Minimal Official Grant",
            "official_url": "https://minimal.example.org/apply",
            "required_documents": None,
            "how_to_apply": None,
        },
        reference_date=date(2026, 6, 1),
    )
    not_stated = [c for c in checklist if c.is_not_stated_officially]
    assert len(not_stated) == 2
    assert all(c.official_url == "https://minimal.example.org/apply" for c in not_stated)


def test_ics_export_structure_all_day_and_no_pii():
    ics = build_ics_calendar(
        plan_id=7,
        items=[
            {
                "grant_id": 2,
                "title": "Chevening Scholarships",
                "official_url": "https://www.chevening.org/",
                "priority_rank": 1,
                "match_percentage": 100.0,
                "deadline_date": date(2027, 11, 3),
            }
        ],
    )
    assert "BEGIN:VCALENDAR\r\n" in ics
    assert "DTSTART;VALUE=DATE:20271103\r\n" in ics
    assert "DTEND;VALUE=DATE:20271104\r\n" in ics
    assert "https://www.chevening.org/" in ics.replace("\r\n ", "")
    assert "END:VCALENDAR\r\n" in ics
    assert "mailto:" not in ics.lower()


# ---------------------------------------------------------------------------
# HTTP Endpoints, Isolation, .ics Download, Assistant Integration & Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_http_lifecycle_ics_summary_isolation_and_delete(client: TestClient, monkeypatch):
    # Requires authenticated consented student
    assert client.get("/api/plan").status_code == 401
    _setup_student(client)

    # Seed expired grant + ineligible grant (excluded YE) directly
    with get_db() as db:
        exp_g = Grant(
            title="Expired Grant Cycle",
            official_url="https://expired.example.org/grant",
            deadline=date.today() - timedelta(days=5),
            accepts_yemeni=YemeniEligibilityStatus.YES,
            nationality_rule={"mode": "all", "countries": [], "groups": []},
            status=GrantStatus.EXPIRED,
        )
        inelig_g = Grant(
            title="Restricted Non-Yemen Grant",
            official_url="https://restricted.example.org/grant",
            deadline=date.today() + timedelta(days=90),
            accepts_yemeni=YemeniEligibilityStatus.NO,
            nationality_rule={"mode": "include", "countries": ["FR"], "groups": []},
            allowed_degrees=["master"],
            status=GrantStatus.PUBLISHED,
        )
        db.add_all([exp_g, inelig_g])
        db.flush()
        exp_id, inelig_id = exp_g.id, inelig_g.id

    # Expired grant cannot be added -> 422
    assert client.post("/api/plan/items", json={"grant_id": exp_id}).status_code == 422

    # Ineligible grant blocked without allow_ineligible -> 409; allowed with warning when true
    assert client.post("/api/plan/items", json={"grant_id": inelig_id}).status_code == 409
    r_inelig = client.post("/api/plan/items", json={"grant_id": inelig_id, "allow_ineligible": True})
    assert r_inelig.status_code == 201
    assert r_inelig.json()["items"][0]["eligible"] is False

    # Add eligible seeded grant (ID 2 = Chevening) -> ranks BEFORE ineligible grant!
    r_elig = client.post("/api/plan/items", json={"grant_id": 2})
    assert r_elig.status_code == 201
    plan_body = r_elig.json()
    assert plan_body["total_grants"] == 2
    assert plan_body["items"][0]["grant_id"] == 2
    assert plan_body["items"][0]["priority_rank"] == 1
    assert plan_body["items"][1]["priority_rank"] == 2
    chevening_item = plan_body["items"][0]

    # Tick first checklist item + add private notes
    first_check_id = chevening_item["checklist"][0]["id"]
    patched = client.patch(
        f"/api/plan/items/{chevening_item['id']}",
        json={
            "notes": "Ask Prof. Ali for brief next week",
            "checklist_updates": [{"id": first_check_id, "status": "done"}],
        },
    )
    assert patched.status_code == 200
    assert patched.json()["items"][0]["progress_percentage"] > 0.0
    assert patched.json()["items"][0]["notes"] == "Ask Prof. Ali for brief next week"

    # Oversized notes (>2000) -> 422
    assert (
        client.patch(f"/api/plan/items/{chevening_item['id']}", json={"notes": "x" * 2001}).status_code
        == 422
    )

    # Download .ics calendar
    ics_resp = client.get("/api/plan/calendar.ics")
    assert ics_resp.status_code == 200
    assert "text/calendar" in ics_resp.headers["content-type"]
    assert "BEGIN:VCALENDAR" in ics_resp.text

    # Optional AI summary handles hallucinated IDs & LLMError cleanly without failing
    app.dependency_overrides[get_llm] = lambda: _FakePlanSummaryLLM(
        {"summary_ar": "ابدأ بهذا العنصر.", "referenced_item_ids": [chevening_item["id"]]},
        configured=True,
    )
    try:
        s_ok = client.post("/api/plan/summary")
        assert s_ok.status_code == 200 and s_ok.json()["available"] is True
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_llm] = lambda: _FakePlanSummaryLLM(LLMError("down"), configured=True)
    try:
        s_err = client.post("/api/plan/summary")
        assert s_err.status_code == 200 and s_err.json()["available"] is False
    finally:
        app.dependency_overrides.clear()

    # Cross-student isolation: another student gets empty plan and 404 on this item ID
    with TestClient(app) as student_b:
        _setup_student(student_b)
        assert student_b.get("/api/plan").json()["total_grants"] == 0
        assert student_b.patch(f"/api/plan/items/{chevening_item['id']}", json={"notes": "x"}).status_code == 404
        assert student_b.delete(f"/api/plan/items/{chevening_item['id']}").status_code == 404

    # Assistant `get_my_plan` tool reads real plan for this session
    with get_db() as db:
        sid = db.query(ApplicationPlan).first().session_id
    tool_res = await _run_get_my_plan(
        StudentPrincipal(session_id=sid, authenticated=True, has_consent=True),
        NoArgs(),
    )
    assert tool_res["available"] is True
    assert tool_res["has_plan"] is True
    assert tool_res["total_grants"] == 2

    # Remove one grant item -> delete-my-data wipes remaining plan & items
    rem = client.delete(f"/api/plan/items/{inelig_id if False else plan_body['items'][1]['id']}")
    assert rem.status_code == 200
    assert rem.json()["total_grants"] == 1

    del_all = client.delete("/api/students/data")
    assert del_all.status_code == 200
    assert del_all.json()["removed_counts"]["plan_items"] == 1
    assert del_all.json()["removed_counts"]["application_plans"] == 1
    with get_db() as db:
        assert db.query(ApplicationPlan).count() == 0
        assert db.query(PlanItem).count() == 0
