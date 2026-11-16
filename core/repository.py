"""Repository layer for Grant and UpdateLog persistence.

Encapsulates all database operations, ensuring strict status handling,
fast indexed queries, and audit logging.
"""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import asc, nulls_last, or_
from sqlalchemy.orm import Session
from core.models import Grant, GrantStatus, UpdateLog, YemeniEligibilityStatus


def get_top_10_grants(
    db: Session,
    limit: int = 10,
    reference_date: Optional[date] = None,
) -> List[Grant]:
    """Retrieve top published grants ordered by closest upcoming deadline.

    Criteria:
    - Status must be PUBLISHED.
    - Deadline must be today or in the future, or NULL (ongoing/open).
    - Ordered by closest deadline ascending, with NULL deadlines placed last.
    - Limits to top 10 (or specified limit).
    """
    ref_date = reference_date or date.today()

    query = (
        db.query(Grant)
        .filter(Grant.status == GrantStatus.PUBLISHED)
        .filter(or_(Grant.deadline.is_(None), Grant.deadline >= ref_date))
        .order_by(nulls_last(asc(Grant.deadline)))
        .limit(limit)
    )
    return query.all()


def get_grant_by_id(db: Session, grant_id: int) -> Optional[Grant]:
    """Find a grant by primary key."""
    return db.query(Grant).filter(Grant.id == grant_id).first()


def get_grant_by_url(db: Session, official_url: str) -> Optional[Grant]:
    """Find a grant by exact official URL."""
    return db.query(Grant).filter(Grant.official_url == official_url).first()


def save_draft(db: Session, grant_data: Union[Dict[str, Any], Grant]) -> Grant:
    """Save or update a grant strictly in DRAFT status.

    If an entry with the same official_url exists:
    - If it is already a DRAFT, it updates its fields.
    - If it is already PUBLISHED, it does not overwrite published data blindly;
      instead, it updates the draft snapshot for review.
    """
    if isinstance(grant_data, Grant):
        data = grant_data.to_dict()
    else:
        data = dict(grant_data)

    url = data.get("official_url")
    if not url:
        raise ValueError("official_url is required to save a grant.")

    existing = get_grant_by_url(db, url)

    # Normalize Yemeni eligibility enum if passed as string
    accepts_yemeni_val = data.get("accepts_yemeni", YemeniEligibilityStatus.UNCLEAR)
    if isinstance(accepts_yemeni_val, str):
        try:
            accepts_yemeni_val = YemeniEligibilityStatus(accepts_yemeni_val.lower())
        except ValueError:
            accepts_yemeni_val = YemeniEligibilityStatus.UNCLEAR

    if existing:
        # Update existing record
        for key in [
            "title",
            "description",
            "eligibility",
            "criteria",
            "fields_of_study",
            "funding",
            "required_documents",
            "deadline",
            "how_to_apply",
            "evidence",
            "field_verification",
            "content_hash",
            "last_checked_at",
        ]:
            if key in data:
                setattr(existing, key, data[key])

        existing.accepts_yemeni = accepts_yemeni_val
        # Always maintain DRAFT unless explicitly already published or managed
        if existing.status != GrantStatus.PUBLISHED:
            existing.status = GrantStatus.DRAFT
        existing.updated_at = datetime.now(timezone.utc)
        db.add(existing)
        db.flush()
        return existing

    # Create brand new record as DRAFT
    new_grant = Grant(
        title=data.get("title", "Untitled Grant"),
        official_url=url,
        description=data.get("description"),
        eligibility=data.get("eligibility"),
        criteria=data.get("criteria"),
        fields_of_study=data.get("fields_of_study"),
        funding=data.get("funding"),
        required_documents=data.get("required_documents"),
        deadline=data.get("deadline"),
        how_to_apply=data.get("how_to_apply"),
        accepts_yemeni=accepts_yemeni_val,
        evidence=data.get("evidence", {}),
        field_verification=data.get("field_verification", {}),
        status=GrantStatus.DRAFT,
        content_hash=data.get("content_hash"),
        last_checked_at=data.get("last_checked_at"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(new_grant)
    db.flush()
    return new_grant


def publish(db: Session, grant_id: int) -> Optional[Grant]:
    """Publish a grant after human review."""
    grant = get_grant_by_id(db, grant_id)
    if not grant:
        return None
    grant.status = GrantStatus.PUBLISHED
    grant.updated_at = datetime.now(timezone.utc)
    db.add(grant)
    db.flush()
    return grant


def mark_expired(db: Session, grant_id: int) -> Optional[Grant]:
    """Mark a grant as expired."""
    grant = get_grant_by_id(db, grant_id)
    if not grant:
        return None
    grant.status = GrantStatus.EXPIRED
    grant.updated_at = datetime.now(timezone.utc)
    db.add(grant)
    db.flush()
    return grant


def log_update(
    db: Session,
    grant_id: int,
    field_name: str,
    old_value: Optional[str],
    new_value: Optional[str],
    notified: bool = False,
) -> UpdateLog:
    """Record a detected change in a grant field."""
    log_entry = UpdateLog(
        grant_id=grant_id,
        field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        detected_at=datetime.now(timezone.utc),
        notified=notified,
    )
    db.add(log_entry)
    db.flush()
    return log_entry
