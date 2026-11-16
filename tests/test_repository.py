"""Unit tests for repository layer and database models.

Verifies:
- Top 10 retrieval logic (published only, non-expired, ordered by closest deadline, max 10).
- Draft and expired grants are excluded from top 10.
- save_draft, publish, and log_update lifecycle methods.
"""

from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.models import Base, Grant, GrantStatus, UpdateLog, YemeniEligibilityStatus
from core.repository import (
    get_grant_by_id,
    get_grant_by_url,
    get_top_10_grants,
    log_update,
    mark_expired,
    publish,
    save_draft,
)


@pytest.fixture
def db_session():
    """Create an isolated in-memory SQLite database for each test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_save_draft_creates_draft_status(db_session):
    """Ensure any grant saved via save_draft starts as DRAFT."""
    grant_data = {
        "title": "Türkiye Bursları 2026",
        "official_url": "https://www.turkiyeburslari.gov.tr/",
        "description": "Turkish government full scholarship.",
        "deadline": date.today() + timedelta(days=60),
        "accepts_yemeni": "yes",
    }
    draft = save_draft(db_session, grant_data)
    db_session.commit()

    assert draft.id is not None
    assert draft.status == GrantStatus.DRAFT
    assert draft.accepts_yemeni == YemeniEligibilityStatus.YES
    assert draft.title == "Türkiye Bursları 2026"


def test_publish_changes_status_to_published(db_session):
    """Ensure publishing promotes a draft to PUBLISHED."""
    grant_data = {
        "title": "Chevening Scholarships",
        "official_url": "https://www.chevening.org/scholarships/",
        "deadline": date.today() + timedelta(days=90),
    }
    draft = save_draft(db_session, grant_data)
    db_session.commit()

    published = publish(db_session, draft.id)
    db_session.commit()

    assert published.status == GrantStatus.PUBLISHED
    fetched = get_grant_by_id(db_session, draft.id)
    assert fetched.status == GrantStatus.PUBLISHED


def test_get_top_10_grants_excludes_drafts_and_expired(db_session):
    """Ensure drafts, expired grants, and past deadlines are strictly excluded."""
    today = date.today()

    # 1. Valid published grant (upcoming deadline)
    g1 = Grant(
        title="Valid Published Grant",
        official_url="https://example.com/published",
        deadline=today + timedelta(days=10),
        status=GrantStatus.PUBLISHED,
    )
    # 2. Draft grant (should NOT appear)
    g2 = Grant(
        title="Draft Grant",
        official_url="https://example.com/draft",
        deadline=today + timedelta(days=5),
        status=GrantStatus.DRAFT,
    )
    # 3. Expired status grant (should NOT appear)
    g3 = Grant(
        title="Expired Status Grant",
        official_url="https://example.com/expired-status",
        deadline=today + timedelta(days=20),
        status=GrantStatus.EXPIRED,
    )
    # 4. Published grant with past deadline (should NOT appear)
    g4 = Grant(
        title="Past Deadline Grant",
        official_url="https://example.com/past-deadline",
        deadline=today - timedelta(days=2),
        status=GrantStatus.PUBLISHED,
    )

    db_session.add_all([g1, g2, g3, g4])
    db_session.commit()

    top_grants = get_top_10_grants(db_session, reference_date=today)
    assert len(top_grants) == 1
    assert top_grants[0].title == "Valid Published Grant"


def test_get_top_10_grants_orders_by_closest_deadline_and_limits_to_10(db_session):
    """Ensure results are sorted by closest deadline first and capped at 10."""
    today = date.today()

    # Create 15 published grants with varying deadlines
    grants = []
    for i in range(15):
        grants.append(
            Grant(
                title=f"Grant Day +{i * 2}",
                official_url=f"https://example.com/grant-{i}",
                deadline=today + timedelta(days=i * 2),
                status=GrantStatus.PUBLISHED,
            )
        )
    # Add one grant with no deadline (rolling)
    grants.append(
        Grant(
            title="Rolling Grant (No Deadline)",
            official_url="https://example.com/rolling",
            deadline=None,
            status=GrantStatus.PUBLISHED,
        )
    )

    db_session.add_all(grants)
    db_session.commit()

    top_grants = get_top_10_grants(db_session, limit=10, reference_date=today)

    # Must return at most 10 grants
    assert len(top_grants) == 10

    # Must be ordered by closest deadline ascending
    deadlines = [g.deadline for g in top_grants if g.deadline is not None]
    assert deadlines == sorted(deadlines)
    assert top_grants[0].title == "Grant Day +0"
    assert top_grants[1].title == "Grant Day +2"


def test_log_update_records_audit_trail(db_session):
    """Ensure field changes are logged and linked to the grant."""
    grant = save_draft(
        db_session,
        {"title": "DAAD Scholarship", "official_url": "https://daad.de/grant"},
    )
    db_session.commit()

    log_entry = log_update(
        db=db_session,
        grant_id=grant.id,
        field_name="deadline",
        old_value="2026-05-01",
        new_value="2026-06-15",
    )
    db_session.commit()

    assert log_entry.id is not None
    assert log_entry.grant_id == grant.id
    assert log_entry.field_name == "deadline"
    assert log_entry.old_value == "2026-05-01"
    assert log_entry.new_value == "2026-06-15"
    assert log_entry.notified is False

    # Check relation
    assert len(grant.update_logs) == 1
    assert grant.update_logs[0].id == log_entry.id
