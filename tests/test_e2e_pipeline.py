"""End-to-End (E2E) Pipeline Integration Tests (Phase 7).

Tests the complete scholarship lifecycle across all layers:
1. Official URL -> Ingestion Sub-Agent -> Saved as DRAFT (excluded from Top 10).
2. Admin Publish -> Promoted to PUBLISHED (appears in Top 10).
3. Monitor Service -> Detects content/deadline change -> Logs in UpdateLog without overwriting.
4. Imminent Deadline -> Triggers 7-day & 3-day alerts -> Marks EXPIRED after deadline (drops from Top 10).
5. Anti-Hallucination E2E -> Fabricated LLM quote is nullified & flagged 'unverified' before DB save.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Grant, GrantStatus, UpdateLog, YemeniEligibilityStatus
from core.repository import get_top_10_grants, publish
from ingestion_sub_agent import ingest
from monitor_service import check_grant_updates, check_imminent_deadlines
from utils.llm_extractor import GrantExtractionSchema, LLMClient


@pytest.fixture
def e2e_db():
    """Isolated in-memory SQLite database for full E2E pipeline verification."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_full_e2e_lifecycle_ingest_publish_top10_monitor(e2e_db):
    """Run complete E2E flow: URL -> Draft -> Publish -> Top 10 -> Monitor -> Expire."""
    ref_today = date(2026, 11, 17)
    initial_deadline = ref_today + timedelta(days=30)  # 2026-12-17

    official_html = f"""
    <html>
      <head><title>DAAD Master Fellowship 2026</title></head>
      <body>
        <h1>DAAD Master Fellowship 2026</h1>
        <p>Funded by the German Federal Foreign Office for international postgraduate students.</p>
        <p>Eligibility: Citizens of developing countries including Yemen are eligible to apply.</p>
        <p>Funding: Full tuition waiver and monthly stipend of EUR 934.</p>
        <p>Deadline: {initial_deadline.isoformat()}.</p>
      </body>
    </html>
    """

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate_structured.return_value = GrantExtractionSchema(
        title="DAAD Master Fellowship 2026",
        description="Funded by the German Federal Foreign Office for international postgraduate students.",
        eligibility=["Citizens of developing countries including Yemen are eligible to apply."],
        funding="Full tuition waiver and monthly stipend of EUR 934.",
        deadline=initial_deadline.isoformat(),
        accepts_yemeni="yes",
        evidence={
            "title": "DAAD Master Fellowship 2026",
            "description": "Funded by the German Federal Foreign Office for international postgraduate students.",
            "eligibility": "Citizens of developing countries including Yemen are eligible to apply.",
            "funding": "Full tuition waiver and monthly stipend of EUR 934.",
            "deadline": initial_deadline.isoformat(),
            "accepts_yemeni": "Citizens of developing countries including Yemen are eligible to apply.",
        },
    )

    # 1. INGEST -> Must save strictly as DRAFT
    draft_grant = ingest(
        official_url="https://www.daad.de/en/master-fellowship-2026",
        db=e2e_db,
        client=mock_llm,
        page_html_override=official_html,
        skip_url_validation=True,
    )
    e2e_db.commit()

    assert draft_grant.status == GrantStatus.DRAFT
    assert draft_grant.accepts_yemeni == YemeniEligibilityStatus.YES
    assert draft_grant.field_verification["funding"] == "verified"

    # Draft MUST NOT appear in get_top_10_grants
    assert len(get_top_10_grants(e2e_db, reference_date=ref_today)) == 0

    # 2. ADMIN PUBLISH -> Promoted to PUBLISHED & appears in Top 10
    published_grant = publish(e2e_db, draft_grant.id)
    e2e_db.commit()

    assert published_grant.status == GrantStatus.PUBLISHED
    top_10 = get_top_10_grants(e2e_db, reference_date=ref_today)
    assert len(top_10) == 1
    assert top_10[0].id == published_grant.id

    # 3. MONITOR DETECTS CHANGE -> Logs to UpdateLog without overwriting published deadline
    new_deadline = initial_deadline + timedelta(days=15)
    change_report = check_grant_updates(
        grant=published_grant,
        db=e2e_db,
        page_fetcher=lambda url: f"Updated page: Deadline extended to {new_deadline.isoformat()}",
        extracted_deadline_override=new_deadline,
    )
    e2e_db.commit()

    assert change_report is not None
    assert any("deadline:" in item for item in change_report["changes"])

    # Verify UpdateLog recorded the deadline change
    logs = e2e_db.query(UpdateLog).filter(UpdateLog.grant_id == published_grant.id).all()
    assert any(l.field_name == "deadline" and l.new_value == new_deadline.isoformat() for l in logs)

    # Published grant deadline MUST remain unchanged until admin approves
    e2e_db.refresh(published_grant)
    assert published_grant.deadline == initial_deadline

    # 4. MONITOR IMMINENT DEADLINE ALERTS (7 days & 3 days)
    alerts_7d = check_imminent_deadlines(e2e_db, reference_date=initial_deadline - timedelta(days=7))
    assert any(a["alert_type"] == "CLOSING_SOON_7_DAYS" for a in alerts_7d)

    alerts_3d = check_imminent_deadlines(e2e_db, reference_date=initial_deadline - timedelta(days=3))
    assert any(a["alert_type"] == "CLOSING_SOON_URGENT" for a in alerts_3d)

    # 5. EXPIRATION -> Past deadline marks EXPIRED and drops from Top 10
    alerts_exp = check_imminent_deadlines(e2e_db, reference_date=initial_deadline + timedelta(days=1))
    e2e_db.commit()
    assert any(a["alert_type"] == "GRANT_EXPIRED" for a in alerts_exp)

    e2e_db.refresh(published_grant)
    assert published_grant.status == GrantStatus.EXPIRED
    assert len(get_top_10_grants(e2e_db, reference_date=initial_deadline + timedelta(days=1))) == 0


def test_e2e_anti_hallucination_catches_fabricated_fields(e2e_db):
    """Intentionally feed a sparse page with a hallucinating LLM to prove code nullifies lies."""
    sparse_html = """
    <html>
      <body>
        <h1>National Merit Award 2027</h1>
        <p>More details about eligibility and funding will be published next quarter.</p>
      </body>
    </html>
    """

    hallucinating_llm = MagicMock(spec=LLMClient)
    hallucinating_llm.generate_structured.return_value = GrantExtractionSchema(
        title="National Merit Award 2027",
        funding="Full scholarship plus $2,000 monthly cash grant",  # Hallucinated!
        deadline="2027-05-01",  # Hallucinated!
        accepts_yemeni="yes",  # Hallucinated!
        evidence={
            "title": "National Merit Award 2027",
            "funding": "Provides $2,000 per month to all winners",  # Fabricated quote!
            "deadline": "Apply before May 1, 2027",  # Fabricated quote!
            "accepts_yemeni": "Open exclusively to Yemeni applicants",  # Fabricated quote!
        },
    )

    saved_grant = ingest(
        official_url="https://education.gov/national-merit-2027",
        db=e2e_db,
        client=hallucinating_llm,
        page_html_override=sparse_html,
        skip_url_validation=True,
    )
    e2e_db.commit()

    # Code verification MUST nullify fabricated fields and mark them unverified
    assert saved_grant.status == GrantStatus.DRAFT
    assert saved_grant.title == "National Merit Award 2027"
    assert saved_grant.field_verification["title"] == "verified"

    assert saved_grant.funding is None
    assert saved_grant.field_verification["funding"] == "unverified"

    assert saved_grant.deadline is None
    assert saved_grant.field_verification["deadline"] == "unverified"

    # Unverified Yemeni claim MUST fall back to UNCLEAR
    assert saved_grant.accepts_yemeni == YemeniEligibilityStatus.UNCLEAR
    assert saved_grant.field_verification["accepts_yemeni"] == "unverified"
