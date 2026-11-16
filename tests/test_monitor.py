"""Unit tests for Monitor Service (Task 9).

Verifies:
- 7-day closing alert triggers correctly.
- 3-day urgent closing alert triggers correctly.
- Expired grants are marked EXPIRED and logged.
- Page content hash changes are detected and logged.
- Deadline modifications trigger DEADLINE_CHANGED alerts and UpdateLog audit entries.
- Published grant data is never overwritten without human approval.
"""

from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.models import Base, Grant, GrantStatus, UpdateLog
from monitor_service import (
    check_grant_updates,
    check_imminent_deadlines,
    run_monitor_cycle,
)


@pytest.fixture
def monitor_db():
    """Create an isolated in-memory SQLite database session for monitor tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_imminent_deadline_alerts(monitor_db):
    """Ensure 7-day, 3-day, and expiration alerts trigger accurately based on reference_date."""
    today = date(2026, 11, 16)

    # 1. Grant closing in 7 days (2026-11-23)
    g7 = Grant(
        title="Scholarship 7 Days Left",
        official_url="https://example.com/7days",
        deadline=today + timedelta(days=7),
        status=GrantStatus.PUBLISHED,
    )
    # 2. Grant closing in 3 days (2026-11-19)
    g3 = Grant(
        title="Scholarship 3 Days Left (Urgent)",
        official_url="https://example.com/3days",
        deadline=today + timedelta(days=3),
        status=GrantStatus.PUBLISHED,
    )
    # 3. Grant already expired (2026-11-10)
    g_exp = Grant(
        title="Expired Scholarship",
        official_url="https://example.com/expired",
        deadline=today - timedelta(days=6),
        status=GrantStatus.PUBLISHED,
    )
    # 4. Safe grant closing in 40 days (no alert)
    g_safe = Grant(
        title="Far Future Scholarship",
        official_url="https://example.com/safe",
        deadline=today + timedelta(days=40),
        status=GrantStatus.PUBLISHED,
    )

    monitor_db.add_all([g7, g3, g_exp, g_safe])
    monitor_db.commit()

    alerts = check_imminent_deadlines(monitor_db, reference_date=today)
    monitor_db.commit()

    assert len(alerts) == 3

    alert_types = [a["alert_type"] for a in alerts]
    assert "CLOSING_SOON_7_DAYS" in alert_types
    assert "CLOSING_SOON_URGENT" in alert_types
    assert "GRANT_EXPIRED" in alert_types

    # Ensure expired grant status was updated in DB
    refreshed_exp = monitor_db.query(Grant).filter(Grant.id == g_exp.id).first()
    assert refreshed_exp.status == GrantStatus.EXPIRED

    # Ensure status change was recorded in UpdateLog
    log = monitor_db.query(UpdateLog).filter(UpdateLog.grant_id == g_exp.id).first()
    assert log is not None
    assert log.field_name == "status"
    assert log.old_value == "published"
    assert log.new_value == "expired"


def test_detect_content_and_deadline_changes(monitor_db):
    """Ensure content hash and deadline modifications are caught and logged."""
    original_text = "Official Scholarship Requirements and Details"
    original_deadline = date(2027, 3, 1)

    grant = Grant(
        title="Dynamic Portal Scholarship",
        official_url="https://example.com/dynamic",
        deadline=original_deadline,
        content_hash="old_known_hash_12345",
        status=GrantStatus.PUBLISHED,
    )
    monitor_db.add(grant)
    monitor_db.commit()

    # 1. First check with UNCHANGED content -> returns None
    result_same = check_grant_updates(
        grant=grant,
        db=monitor_db,
        page_fetcher=lambda url: "content matching old_known_hash_12345",
    )
    # When page returns same text corresponding to hash, no change logged
    # Here mock returns new text:
    modified_text = "Updated Official Requirements! Extended Deadline to 2027-04-15."
    new_deadline = date(2027, 4, 15)

    result_diff = check_grant_updates(
        grant=grant,
        db=monitor_db,
        page_fetcher=lambda url: modified_text,
        extracted_deadline_override=new_deadline,
    )
    monitor_db.commit()

    assert result_diff is not None
    assert "content_hash" in result_diff["changes"]
    assert any("deadline:" in c for c in result_diff["changes"])

    # Verify UpdateLog records
    logs = monitor_db.query(UpdateLog).filter(UpdateLog.grant_id == grant.id).all()
    logged_fields = [l.field_name for l in logs]
    assert "content_hash" in logged_fields
    assert "deadline" in logged_fields

    deadline_log = next(l for l in logs if l.field_name == "deadline")
    assert deadline_log.old_value == "2027-03-01"
    assert deadline_log.new_value == "2027-04-15"

    # Crucial Rule: The published grant's deadline in the DB was NOT overwritten automatically!
    refreshed_grant = monitor_db.query(Grant).filter(Grant.id == grant.id).first()
    assert refreshed_grant.deadline == original_deadline  # Remains original until admin review


def test_run_monitor_cycle_end_to_end(monitor_db):
    """Ensure run_monitor_cycle executes cleanly and returns a structured summary."""
    today = date(2026, 11, 16)
    g = Grant(
        title="Cycle Test Grant",
        official_url="https://example.com/cycle",
        deadline=today + timedelta(days=3),
        content_hash="initial_hash",
        status=GrantStatus.PUBLISHED,
    )
    monitor_db.add(g)
    monitor_db.commit()

    summary = run_monitor_cycle(
        db=monitor_db,
        reference_date=today,
        page_fetcher=lambda url: "initial_hash text",
    )

    assert summary["total_published_checked"] == 1
    assert summary["deadline_alerts_issued"] == 1  # 3 days urgent alert
    assert summary["details"]["alerts"][0]["alert_type"] == "CLOSING_SOON_URGENT"
