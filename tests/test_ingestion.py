"""Unit tests for Ingestion Sub-Agent (Task 2).

Verifies:
- Offline HTML fixture ingestion saves as DRAFT.
- Sub-link detection correctly filters same-domain criteria links.
- Incomplete pages result in null fields rather than hallucinations.
- Content hash computation is deterministic.
"""

from datetime import date
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.models import Base, GrantStatus, YemeniEligibilityStatus
from ingestion_sub_agent import (
    compute_content_hash,
    extract_text_and_links,
    find_relevant_sublink,
    ingest,
)
from utils.llm_extractor import GrantExtractionSchema, LLMClient


@pytest.fixture
def test_db_session():
    """Create an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_compute_content_hash_deterministic():
    """Ensure SHA-256 hash is consistent for identical content."""
    text1 = "Scholarship details text"
    text2 = "Scholarship details text"
    text3 = "Different text"

    assert compute_content_hash(text1) == compute_content_hash(text2)
    assert compute_content_hash(text1) != compute_content_hash(text3)


def test_find_relevant_sublink_identifies_criteria_links():
    """Ensure sub-link crawler identifies relevant criteria links on same domain."""
    base_url = "https://www.daad.de/en/scholarships/"
    links = [
        {"url": "https://www.daad.de/en/contact", "text": "Contact Us"},
        {"url": "https://facebook.com/daad", "text": "Facebook"},  # Different domain
        {"url": "https://www.daad.de/en/scholarships/application-requirements", "text": "Application Requirements"},
        {"url": "https://www.daad.de/en/scholarships/funding-overview", "text": "Funding Overview"},
    ]

    sublink = find_relevant_sublink(base_url, links)
    assert sublink == "https://www.daad.de/en/scholarships/application-requirements"


def test_ingest_with_offline_html_fixture(test_db_session):
    """Test full ingestion pipeline using an offline HTML fixture without internet."""
    html_fixture = """
    <!DOCTYPE html>
    <html>
        <head><title>Stipendium Hungaricum Scholarship</title></head>
        <body>
            <h1>Stipendium Hungaricum Programme 2026</h1>
            <p>The Stipendium Hungaricum scholarship programme was launched by the Hungarian Government.</p>
            <div class="eligibility">
                <h2>Eligibility Criteria</h2>
                <p>Citizens of eligible partner countries including Yemen are eligible to apply.</p>
            </div>
            <div class="funding">
                <h2>Provisions</h2>
                <p>Full tuition fee exemption, monthly stipend, and dormitory placement or accommodation allowance.</p>
            </div>
            <div class="deadline">
                <p>Submission deadline: 2026-01-15 14:00 CET.</p>
            </div>
        </body>
    </html>
    """

    # Mock LLM Client that returns valid schema with verbatim quotes from the fixture
    mock_llm_client = MagicMock(spec=LLMClient)
    mock_llm_client.generate_structured.return_value = GrantExtractionSchema(
        title="Stipendium Hungaricum Programme 2026",
        description="The Stipendium Hungaricum scholarship programme was launched by the Hungarian Government.",
        eligibility=["Citizens of eligible partner countries including Yemen are eligible to apply."],
        funding="Full tuition fee exemption, monthly stipend, and dormitory placement",
        deadline="2026-01-15",
        accepts_yemeni="yes",
        evidence={
            "title": "Stipendium Hungaricum Programme 2026",
            "description": "The Stipendium Hungaricum scholarship programme was launched by the Hungarian Government.",
            "eligibility": "Citizens of eligible partner countries including Yemen are eligible to apply.",
            "funding": "Full tuition fee exemption, monthly stipend, and dormitory placement",
            "deadline": "2026-01-15",
        },
    )

    grant = ingest(
        official_url="https://stipendiumhungaricum.hu/apply",
        db=test_db_session,
        client=mock_llm_client,
        page_html_override=html_fixture,
        skip_url_validation=True,
    )
    test_db_session.commit()

    # Verify grant status and properties
    assert grant.id is not None
    assert grant.status == GrantStatus.DRAFT  # Must be saved as DRAFT
    assert grant.title == "Stipendium Hungaricum Programme 2026"
    assert grant.deadline == date(2026, 1, 15)
    assert grant.accepts_yemeni == YemeniEligibilityStatus.YES
    assert grant.field_verification.get("funding") == "verified"
    assert grant.field_verification.get("eligibility") == "verified"
    assert grant.content_hash is not None


def test_ingest_incomplete_page_yields_nulls_not_guesses(test_db_session):
    """Ensure an incomplete page results in null fields, avoiding hallucinated values."""
    sparse_html = """
    <html>
        <body>
            <h1>Minimal Scholarship Announcement</h1>
            <p>Details regarding funding and deadlines will be announced soon.</p>
        </body>
    </html>
    """

    # Mock LLM that returns nulls for missing details
    mock_llm_client = MagicMock(spec=LLMClient)
    mock_llm_client.generate_structured.return_value = GrantExtractionSchema(
        title="Minimal Scholarship Announcement",
        description=None,
        funding=None,
        deadline=None,
        eligibility=None,
        accepts_yemeni="unclear",
        evidence={"title": "Minimal Scholarship Announcement"},
    )

    grant = ingest(
        official_url="https://example.gov/sparse-grant",
        db=test_db_session,
        client=mock_llm_client,
        page_html_override=sparse_html,
        skip_url_validation=True,
    )
    test_db_session.commit()

    assert grant.status == GrantStatus.DRAFT
    assert grant.funding is None
    assert grant.deadline is None
    assert grant.eligibility is None
    assert grant.accepts_yemeni == YemeniEligibilityStatus.UNCLEAR
