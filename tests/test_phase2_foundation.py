"""Phase 2 foundation verification tests.

Covers:
1. Ordered migrations: fresh install vs upgrade from Phase 1 seeded schema reach identical schema.
2. Unified LLM boundary (`modules/llm/`): mock 200, 400 (no retry + fallback), 429/500/timeout retries,
   structured 1 validation retry, no keys/prompts in logs, and legacy ingestion compatibility.
3. Generic nationality rule evaluation (`evaluate_nationality`) and Yemen consistency.
4. Curated Top 10 ordering (`featured_rank` priority, deadline tiebreak, expired/draft exclusion, <10).
5. Featured rank endpoint authorization & validation.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, inspect, text

import core.db as core_db
from core.models import Grant, GrantStatus, YemeniEligibilityStatus
from core.repository import get_top_10_grants, publish, save_draft
from ingestion_sub_agent import ingest
from migrations.runner import get_applied_migrations, run_migrations
from modules.llm.client import AsyncLLMClient, LLMClient, LLMError
from modules.matching.gpa import normalize_gpa_to_4
from modules.matching.nationalities import evaluate_nationality
from seed.seed_db import VERIFIED_TOP10_BASELINE
from utils.llm_extractor import extract_grant_from_text


@pytest.fixture()
def db_session():
    run_migrations(core_db.engine)
    with core_db.get_db() as session:
        yield session


@pytest.fixture()
def auth_headers(monkeypatch: pytest.MonkeyPatch) -> Dict[str, str]:
    from core.config import settings

    admin_key = "test-admin-phase2-secret-999"
    monkeypatch.setenv("ADMIN_API_KEY", admin_key)
    monkeypatch.setattr(settings, "ADMIN_API_KEY", admin_key)
    return {"X-Admin-Key": admin_key}


@pytest.fixture()
def client():
    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _snapshot_schema(engine) -> Dict[str, object]:
    insp = inspect(engine)
    tables = {}
    for tname in sorted(insp.get_table_names()):
        cols = [
            (col["name"], str(col["type"]).upper(), bool(col["nullable"]))
            for col in sorted(insp.get_columns(tname), key=lambda c: c["name"])
        ]
        idxs = sorted(
            (idx["name"], tuple(idx["column_names"]), bool(idx["unique"]))
            for idx in insp.get_indexes(tname)
        )
        tables[tname] = {"columns": cols, "indexes": idxs}
    return tables


def test_migrations_fresh_and_upgrade_seeded_reach_identical_schema(tmp_path):
    """Verify both fresh DB and Phase-1 seeded DB upgrade cleanly to identical schema."""
    from migrations.runner import MIGRATIONS

    expected_versions = [m.VERSION for m in MIGRATIONS]
    fresh_db = tmp_path / "fresh.db"
    fresh_engine = create_engine(f"sqlite:///{fresh_db}")
    applied_fresh = run_migrations(fresh_engine)
    assert applied_fresh == expected_versions
    assert run_migrations(fresh_engine) == []  # Idempotent second pass

    # Build a legacy Phase 1 database WITHOUT schema_migrations and WITHOUT Phase 2 columns
    legacy_db = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{legacy_db}")
    with legacy_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE grants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title VARCHAR(500) NOT NULL,
                    official_url VARCHAR(1000) NOT NULL,
                    description TEXT,
                    eligibility JSON,
                    criteria JSON,
                    fields_of_study JSON,
                    funding TEXT,
                    required_documents JSON,
                    deadline DATE,
                    how_to_apply TEXT,
                    accepts_yemeni VARCHAR(7) NOT NULL,
                    evidence JSON NOT NULL,
                    field_verification JSON NOT NULL,
                    status VARCHAR(9) NOT NULL,
                    content_hash VARCHAR(64),
                    last_checked_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX ix_grants_official_url ON grants (official_url)"))
        conn.execute(text("CREATE INDEX ix_grants_deadline ON grants (deadline)"))
        conn.execute(text("CREATE INDEX ix_grants_status ON grants (status)"))
        conn.execute(text("CREATE INDEX ix_grants_status_deadline ON grants (status, deadline)"))
        conn.execute(
            text(
                """
                CREATE TABLE update_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    grant_id INTEGER NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
                    field_name VARCHAR(100) NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    detected_at DATETIME NOT NULL,
                    notified BOOLEAN NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX ix_update_logs_grant_id ON update_logs (grant_id)"))

        now_iso = datetime.now(timezone.utc).isoformat()
        for entry in VERIFIED_TOP10_BASELINE:
            conn.execute(
                text(
                    """
                    INSERT INTO grants (
                        title, official_url, description, eligibility, criteria,
                        fields_of_study, funding, required_documents, deadline, how_to_apply,
                        accepts_yemeni, evidence, field_verification, status, content_hash,
                        created_at, updated_at
                    ) VALUES (
                        :title, :official_url, :description, :eligibility, :criteria,
                        :fields_of_study, :funding, :required_documents, :deadline, :how_to_apply,
                        'YES', :evidence, :field_verification, 'PUBLISHED', 'seedhash',
                        :now_iso, :now_iso
                    )
                    """
                ),
                {
                    "title": entry["title"],
                    "official_url": entry["official_url"],
                    "description": entry.get("description"),
                    "eligibility": json.dumps(entry.get("eligibility")),
                    "criteria": json.dumps(entry.get("criteria")),
                    "fields_of_study": json.dumps(entry.get("fields_of_study")),
                    "funding": entry.get("funding"),
                    "required_documents": json.dumps(entry.get("required_documents")),
                    "deadline": entry["deadline"].isoformat() if entry.get("deadline") else None,
                    "how_to_apply": entry.get("how_to_apply"),
                    "evidence": json.dumps(entry.get("evidence") or {}),
                    "field_verification": json.dumps(entry.get("field_verification") or {}),
                    "now_iso": now_iso,
                },
            )

    applied_upgrade = run_migrations(legacy_engine)
    assert applied_upgrade == expected_versions

    fresh_schema = _snapshot_schema(fresh_engine)
    upgraded_schema = _snapshot_schema(legacy_engine)
    assert fresh_schema == upgraded_schema

    fresh_versions = [m["version"] for m in get_applied_migrations(fresh_engine)]
    upgraded_versions = [m["version"] for m in get_applied_migrations(legacy_engine)]
    assert fresh_versions == upgraded_versions == [str(v) for v in expected_versions]

    with legacy_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT official_url, host_country, min_gpa_value, min_work_years, nationality_rule "
                "FROM grants"
            )
        ).mappings().all()
        assert len(rows) == 10
        by_url = {r["official_url"]: r for r in rows}
        assert by_url["https://www.turkiyeburslari.gov.tr/"]["min_gpa_value"] == 70.0
        assert by_url["https://www.chevening.org/scholarships/"]["min_work_years"] == 2.0
        romania_rule = json.loads(by_url["https://www.mae.ro/en/node/10250"]["nationality_rule"])
        assert evaluate_nationality("YE", romania_rule) == "yes"
        assert evaluate_nationality("FR", romania_rule) == "no"


def test_nationality_rule_evaluator_and_gpa_normalization():
    """Verify generic nationality rule evaluation and deterministic GPA scaling."""
    assert evaluate_nationality("YE", {"mode": "all"}) == "yes"
    assert evaluate_nationality("DE", {"mode": "all", "countries": ["DE"]}) == "no"
    assert evaluate_nationality("ye", {"mode": "include", "countries": ["YE", "JO"]}) == "yes"
    assert evaluate_nationality("FR", {"mode": "include", "countries": ["YE", "JO"]}) == "no"
    assert evaluate_nationality("YE", {"mode": "exclude", "groups": ["eu"]}) == "yes"
    assert evaluate_nationality("DE", {"mode": "exclude", "groups": ["eu"]}) == "no"
    assert evaluate_nationality("YE", {"mode": "group", "groups": ["isdb_members"]}) == "yes"
    assert evaluate_nationality("JP", {"mode": "group", "groups": ["isdb_members"]}) == "no"
    assert evaluate_nationality("YE", {"mode": "unclear"}) == "unclear"
    assert evaluate_nationality("YE", None) == "unclear"

    assert normalize_gpa_to_4(3.5, "4.0") == 3.5
    assert normalize_gpa_to_4(4.0, "5.0") == 3.2
    assert normalize_gpa_to_4(70.0, "100") == 2.75
    assert normalize_gpa_to_4(None, "100") is None


def test_top10_curation_ordering_priority_and_tiebreaks(db_session):
    """Top 10 puts curated featured_rank first, breaks ties by deadline, excludes draft/expired."""
    today = date.today()
    g_late_featured = save_draft(
        db_session,
        {
            "title": "Featured #1 Late Deadline",
            "official_url": "https://example.org/f1",
            "deadline": today + timedelta(days=90),
            "featured_rank": 1,
        },
    )
    publish(db_session, g_late_featured.id)

    g_featured_2 = save_draft(
        db_session,
        {
            "title": "Featured #2 Earlier Deadline",
            "official_url": "https://example.org/f2",
            "deadline": today + timedelta(days=5),
            "featured_rank": 2,
        },
    )
    publish(db_session, g_featured_2.id)

    g_auto_soon = save_draft(
        db_session,
        {
            "title": "Unfeatured Soonest",
            "official_url": "https://example.org/u1",
            "deadline": today + timedelta(days=2),
        },
    )
    publish(db_session, g_auto_soon.id)

    g_auto_rolling = save_draft(
        db_session,
        {
            "title": "Unfeatured Rolling",
            "official_url": "https://example.org/u2",
            "deadline": None,
        },
    )
    publish(db_session, g_auto_rolling.id)

    # Draft even with featured_rank=1 must be excluded
    save_draft(
        db_session,
        {
            "title": "Draft Featured Excluded",
            "official_url": "https://example.org/d1",
            "deadline": today + timedelta(days=1),
            "featured_rank": 1,
        },
    )

    # Expired grant excluded even if status=PUBLISHED with past deadline
    g_past = save_draft(
        db_session,
        {
            "title": "Past Deadline Grant",
            "official_url": "https://example.org/past",
            "deadline": today - timedelta(days=1),
            "featured_rank": 1,
        },
    )
    publish(db_session, g_past.id)
    db_session.commit()

    top = get_top_10_grants(db_session, limit=10, reference_date=today)
    titles = [g.title for g in top]
    assert titles == [
        "Featured #1 Late Deadline",
        "Featured #2 Earlier Deadline",
        "Unfeatured Soonest",
        "Unfeatured Rolling",
    ]


def test_admin_featured_endpoint_auth_and_update(client: TestClient, auth_headers):
    """PATCH /api/grants/{id}/featured enforces admin auth, validates rank, updates Top 10."""
    # Unauthenticated -> 401
    unauth = client.patch("/api/grants/1/featured", json={"featured_rank": 1})
    assert unauth.status_code == 401

    # Login admin
    admin_key = auth_headers["X-Admin-Key"]
    assert client.post("/api/admin/login", json={"secret": admin_key}).status_code == 200

    # Invalid rank -> 422
    bad = client.patch("/api/grants/1/featured", json={"featured_rank": 99})
    assert bad.status_code == 422

    # Valid rank -> 200 and places grant #10 first in Top 10
    grants = client.get("/api/grants").json()["grants"]
    target_id = grants[-1]["id"]
    ok = client.patch(f"/api/grants/{target_id}/featured", json={"featured_rank": 1})
    assert ok.status_code == 200
    body = ok.json()
    assert body["featured_rank"] == 1
    assert body["is_featured"] is True

    top10 = client.get("/api/grants/top10").json()
    assert top10[0]["id"] == target_id

    # Clear rank -> null
    cleared = client.patch(f"/api/grants/{target_id}/featured", json={"featured_rank": None})
    assert cleared.status_code == 200
    assert cleared.json()["featured_rank"] is None
    assert cleared.json()["is_featured"] is False


class _MiniSchema(BaseModel):
    answer: str


def test_llm_client_retries_429_500_timeout_no_retry_400_and_safe_logs(caplog):
    """Verify exact retry bounds, no retry on 400, fallback model switch, and secret/prompt safety."""
    calls: List[Dict[str, str]] = []
    secret_key = "sk-test-secret-do-not-log-123456"
    secret_prompt_marker = "SECRET_PROMPT_TEXT_MARKER_999"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        model = payload["model"]
        calls.append({"model": model, "auth": request.headers.get("Authorization", "")})

        # Model 1: returns 429 on attempt 0, 500 on attempt 1 -> exhausts retries -> moves to Model 2
        if model == "model-retryable":
            return httpx.Response(429 if len([c for c in calls if c["model"] == model]) == 1 else 500, json={"error": "rate/server"})
        # Model 2: returns 400 Bad Request -> MUST NOT retry same model; immediately moves to Model 3
        if model == "model-bad-request":
            return httpx.Response(400, json={"error": f"bad option {secret_key}"})
        # Model 3: times out once, then succeeds on retry with fenced JSON
        if model == "model-fallback":
            m3_calls = len([c for c in calls if c["model"] == model])
            if m3_calls == 1:
                raise httpx.ReadTimeout("simulated timeout")
            return httpx.Response(
                200,
                json={
                    "model": "model-fallback",
                    "choices": [{"message": {"content": '```json\n{"answer": "ok"}\n```'}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.0002},
                },
            )
        return httpx.Response(500)

    mock_http = httpx.Client(
        base_url="https://mock.llm/v1",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": f"Bearer {secret_key}"},
    )
    client = LLMClient(
        api_key=secret_key,
        models=["model-retryable", "model-bad-request", "model-fallback"],
        backoff_seconds=0.0,
        attempts_per_model=2,
        http=mock_http,
    )

    caplog.set_level(logging.INFO)
    result = client.generate_structured(
        messages=[{"role": "user", "content": secret_prompt_marker}],
        schema=_MiniSchema,
        prompt_version="test_prompt@1.0",
    )
    assert result.answer == "ok"

    # Expected call count: 2 (retryable 429->500) + 1 (400 no retry) + 2 (timeout->200) = 5 calls
    assert [c["model"] for c in calls] == [
        "model-retryable",
        "model-retryable",
        "model-bad-request",
        "model-fallback",
        "model-fallback",
    ]

    log_blob = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "llm ok model=model-fallback prompt=test_prompt@1.0" in log_blob
    assert "in=11 out=7 cost=0.0002" in log_blob
    assert secret_key not in log_blob
    assert secret_prompt_marker not in log_blob


def test_llm_structured_retries_once_on_validation_error_and_raises_llm_error():
    """structured() retries exactly once with validation feedback, then raises LLMError."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        # Always return schema-invalid JSON
        return httpx.Response(
            200,
            json={
                "model": "m1",
                "choices": [{"message": {"content": '{"wrong_field": 123}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    client = LLMClient(
        api_key="test-key",
        models=["m1"],
        backoff_seconds=0.0,
        attempts_per_model=1,
        http=httpx.Client(base_url="https://mock.llm/v1", transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMError):
        client.generate_structured(
            messages=[{"role": "user", "content": "hi"}],
            schema=_MiniSchema,
            prompt_version="test@1",
        )
    assert attempts == 2


def test_legacy_ingest_flow_runs_through_new_boundary_and_nullifies_unverified(db_session):
    """End-to-end ingestion through SyncLLMClient MockTransport verifies structured fields & nulls bad quotes."""
    html_page = """
    <html><body>
      <h1>Atlas Global Master Scholarship</h1>
      <p>Hosted in Germany for master's students. Requires minimum GPA 3.2/4.0 and 2 years experience.</p>
      <p>Citizens of developing countries including Yemen are eligible. Deadline: 2027-06-15.</p>
      <p>Full tuition and monthly stipend provided.</p>
    </body></html>
    """
    payload = {
        "title": "Atlas Global Master Scholarship",
        "description": "Hosted in Germany for master's students.",
        "eligibility": ["Citizens of developing countries including Yemen are eligible."],
        "funding": "Full tuition and monthly stipend provided.",
        "deadline": "2027-06-15",
        "accepts_yemeni": "yes",
        "host_country": "DE",
        "allowed_degrees": ["master"],
        "min_gpa_value": 3.2,
        "min_gpa_scale": "4.0",
        "min_work_years": 2.0,
        "max_age": 28,  # Hallucinated: quote below is NOT in html_page!
        "nationality_rule": {"mode": "group", "countries": ["YE"], "groups": ["developing_countries"]},
        "funding_type": "full",
        "evidence": {
            "title": "Atlas Global Master Scholarship",
            "description": "Hosted in Germany for master's students.",
            "eligibility": "Citizens of developing countries including Yemen are eligible.",
            "funding": "Full tuition and monthly stipend provided.",
            "deadline": "2027-06-15",
            "host_country": "Hosted in Germany",
            "allowed_degrees": "for master's students",
            "min_gpa": "Requires minimum GPA 3.2/4.0",
            "min_work_years": "2 years experience",
            "max_age": "Must be under 28 years old strictly",  # Fabricated quote
            "nationality_rule": "Citizens of developing countries including Yemen are eligible.",
            "funding_type": "Full tuition and monthly stipend provided.",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "mock-model",
                "choices": [{"message": {"content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 80},
            },
        )

    mock_client = LLMClient(
        api_key="test-key",
        models=["mock-model"],
        backoff_seconds=0.0,
        http=httpx.Client(base_url="https://mock.llm/v1", transport=httpx.MockTransport(handler)),
    )

    grant = ingest(
        official_url="https://daad.de/atlas-test",
        db=db_session,
        client=mock_client,
        page_html_override=html_page,
        skip_url_validation=True,
    )
    db_session.commit()

    assert grant.status == GrantStatus.DRAFT
    assert grant.host_country == "DE"
    assert grant.allowed_degrees == ["master"]
    assert grant.min_gpa_value == 3.2
    assert grant.min_gpa_scale == "4.0"
    assert grant.min_gpa_normalized_4 == 3.2
    assert grant.min_work_years == 2.0
    assert grant.max_age is None  # Nullified because quote was fabricated
    assert grant.field_verification.get("max_age") == "unverified"
    assert grant.accepts_yemeni == YemeniEligibilityStatus.YES
    assert evaluate_nationality("YE", grant.nationality_rule) == "yes"
