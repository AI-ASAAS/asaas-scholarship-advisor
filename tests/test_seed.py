"""Unit tests for Seed Database module (Phase 4 / Task 1 & 2).

Verifies:
- Seeding populates 10 valid scholarships with grounded evidence.
- Default seeding creates grants strictly in DRAFT status.
- Publishing grants allows get_top_10_grants() to return exactly 10 grants.
- Results are strictly ordered by closest deadline ascending.
- All 10 scholarships have verified Yemeni eligibility.
"""

from datetime import date
import pytest
from core.db import get_db, init_db
from core.models import Grant, GrantStatus, YemeniEligibilityStatus
from core.repository import get_top_10_grants
from seed.seed_db import publish_reviewed_grant, seed_database


@pytest.fixture(autouse=True)
def setup_clean_db():
    """Ensure database schema is initialized for tests."""
    init_db()


def test_seed_database_creates_10_draft_grants():
    """Ensure seed_database without publish_all keeps all entries in DRAFT status."""
    grants = seed_database(publish_all=False)
    assert len(grants) == 10
    for g in grants:
        assert g.status == GrantStatus.DRAFT
        assert g.accepts_yemeni == YemeniEligibilityStatus.YES
        assert g.evidence is not None
        assert len(g.evidence) > 0


def test_seed_database_with_publish_returns_top_10_in_order():
    """Ensure publishing yields exactly 10 active grants sorted by deadline."""
    grants = seed_database(publish_all=True)
    assert len(grants) == 10

    with get_db() as db:
        top_10 = get_top_10_grants(db, limit=10)
        assert len(top_10) == 10

        # Check all are published
        for g in top_10:
            assert g.status == GrantStatus.PUBLISHED
            assert g.deadline >= date.today()

        # Check ascending order of deadlines
        deadlines = [g.deadline for g in top_10]
        assert deadlines == sorted(deadlines)
        assert top_10[0].deadline <= top_10[-1].deadline


def test_publish_reviewed_grant():
    """Test individual grant publishing by admin."""
    seed_database(publish_all=False)

    with get_db() as db:
        drafts = db.query(Grant).filter(Grant.status == GrantStatus.DRAFT).all()
        assert len(drafts) == 10

    # Publish grant with id 1
    published = publish_reviewed_grant(1)
    assert published is not None
    assert published.status == GrantStatus.PUBLISHED
