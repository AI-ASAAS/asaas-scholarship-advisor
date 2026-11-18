"""Unit tests for Telegram Channel Watcher Integration (Phase 8 Creative Task).

Verifies:
- Regex URL extraction from realistic Arabic/English Telegram posts.
- Rejection of social links (t.me, bit.ly) and unofficial spam aggregators.
- Deduplication within batch and against already-stored database grants.
- Strict hand-off of new official URLs to `ingest()` producing DRAFT grants without
  ever extracting scholarship fields from Telegram post text.
- Fault isolation when one URL fails ingestion.
"""

from datetime import date
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Grant, GrantStatus
from core.repository import save_draft
from ingestion_sub_agent import ingest
from integrations.telegram_watcher import (
    extract_urls_from_text,
    filter_official_urls,
    process_telegram_posts,
)
from utils.llm_extractor import GrantExtractionSchema, LLMClient


@pytest.fixture
def watcher_db():
    """Isolated in-memory SQLite database for Telegram watcher tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_extract_urls_from_arabic_and_english_telegram_posts():
    """Ensure regex extracts clean URLs and strips trailing punctuation."""
    post = """
    📢 عاجل للطلاب اليمنيين! فُتح باب التقديم لمنحة الحكومة المجرية الآن!
    الرابط الرسمي للتقديم: (https://stipendiumhungaricum.hu/apply)،
    ولمعرفة المزيد تابعوا قناتنا: https://t.me/yemen_grants.
    رابط إضافي: https://www.daad.de/en/study-and-research-in-germany/scholarships/!
    """
    urls = extract_urls_from_text(post)
    assert urls == [
        "https://stipendiumhungaricum.hu/apply",
        "https://t.me/yemen_grants",
        "https://www.daad.de/en/study-and-research-in-germany/scholarships/",
    ]


def test_filter_official_urls_rejects_social_and_aggregators():
    """Ensure only trusted official scholarship domains survive filtering."""
    urls = [
        "https://www.chevening.org/scholarships/",
        "https://t.me/yemen_scholarships",
        "https://bit.ly/3fakegrant",
        "https://scholarship-positions.com/chevening-2027/",
        "https://random-blog.xyz/free-money",
        "https://www.turkiyeburslari.gov.tr/",
    ]

    trusted, rejected = filter_official_urls(urls)

    assert trusted == [
        "https://www.chevening.org/scholarships/",
        "https://www.turkiyeburslari.gov.tr/",
    ]
    rejected_urls = [u for u, _ in rejected]
    assert "https://t.me/yemen_scholarships" in rejected_urls
    assert "https://bit.ly/3fakegrant" in rejected_urls
    assert "https://scholarship-positions.com/chevening-2027/" in rejected_urls
    assert "https://random-blog.xyz/free-money" in rejected_urls


def test_process_telegram_posts_deduplicates_and_creates_draft_via_ingest(watcher_db):
    """Test end-to-end Telegram post processing: skips existing & untrusted, ingests new official URL as DRAFT."""
    # Pre-populate DB with one existing scholarship URL
    existing_url = "https://www.turkiyeburslari.gov.tr/"
    save_draft(
        watcher_db,
        {
            "title": "Existing Turkish Scholarship",
            "official_url": existing_url,
            "deadline": date(2027, 2, 20),
        },
    )
    watcher_db.commit()

    # Simulated Telegram posts (note: post makes wild false claim about $50,000 stipend!
    # The watcher MUST IGNORE post text and rely ONLY on official page via ingest()).
    mock_posts = [
        f"منحة تركيا المفتوحة: {existing_url} تابعنا https://t.me/grants_ye",
        "منحة خرافية بـ 50,000 دولار شهرياً! قدم عبر الرابط: https://www.daad.de/en/new-grant-2027",
        # Duplicate of the new grant in a second post + spam aggregator
        "تذكير بالتقديم: https://www.daad.de/en/new-grant-2027 أو https://opportunitiescorners.com/daad",
    ]

    official_html = """
    <html>
      <body>
        <h1>DAAD New Grant 2027</h1>
        <p>Official monthly stipend is EUR 934 for international students including Yemen.</p>
      </body>
    </html>
    """

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate_structured.return_value = GrantExtractionSchema(
        title="DAAD New Grant 2027",
        funding="EUR 934 monthly stipend",
        accepts_yemeni="yes",
        evidence={
            "title": "DAAD New Grant 2027",
            "funding": "Official monthly stipend is EUR 934",
            "accepts_yemeni": "international students including Yemen",
        },
    )

    def offline_ingest(url: str, db):
        return ingest(
            official_url=url,
            db=db,
            client=mock_llm,
            page_html_override=official_html,
            skip_url_validation=True,
        )

    report = process_telegram_posts(mock_posts, db=watcher_db, ingest_fn=offline_ingest)

    assert report["posts_processed"] == 3
    assert report["skipped_existing"] == [existing_url]
    assert len(report["skipped_untrusted"]) == 2  # t.me + opportunitiescorners
    assert len(report["drafts_created"]) == 1
    assert report["errors"] == []

    # Verify the created draft came from official HTML (EUR 934), NOT from Telegram post ($50,000)
    created_id = report["drafts_created"][0]["grant_id"]
    db_grant = watcher_db.query(Grant).filter(Grant.id == created_id).first()
    assert db_grant is not None
    assert db_grant.status == GrantStatus.DRAFT
    assert db_grant.title == "DAAD New Grant 2027"
    assert db_grant.funding == "EUR 934 monthly stipend"


def test_process_telegram_posts_isolates_ingestion_errors(watcher_db):
    """Ensure a single failed URL ingestion does not stop remaining URLs."""
    posts = [
        "Link 1: https://www.daad.de/broken-page",
        "Link 2: https://www.chevening.org/valid-page",
    ]

    def flaky_ingest(url: str, db):
        if "broken" in url:
            raise RuntimeError("Simulated 503 Service Unavailable")
        return save_draft(db, {"title": "Valid Chevening Draft", "official_url": url})

    report = process_telegram_posts(posts, db=watcher_db, ingest_fn=flaky_ingest)

    assert len(report["errors"]) == 1
    assert "broken-page" in report["errors"][0]["url"]
    assert len(report["drafts_created"]) == 1
    assert report["drafts_created"][0]["official_url"] == "https://www.chevening.org/valid-page"
