"""Repository layer for Grant and UpdateLog persistence.

Encapsulates all database operations, ensuring strict status handling,
fast indexed queries, and audit logging.
"""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import asc, case, desc, nulls_last, or_
from sqlalchemy.orm import Session
from core.models import (
    DocumentDraft,
    Grant,
    GrantChangeReview,
    GrantStatus,
    Notification,
    PlanItem,
    UpdateLog,
    YemeniEligibilityStatus,
)
from modules.matching.gpa import normalize_gpa_to_4
from modules.matching.nationalities import evaluate_nationality


def sync_expired_grants(db: Session, reference_date: Optional[date] = None) -> int:
    """Automatically transition published grants past their deadline to EXPIRED status."""
    ref_date = reference_date or date.today()
    expired_rows = (
        db.query(Grant)
        .filter(Grant.status == GrantStatus.PUBLISHED)
        .filter(Grant.deadline.isnot(None))
        .filter(Grant.deadline < ref_date)
        .all()
    )
    if not expired_rows:
        return 0
    now = datetime.now(timezone.utc)
    for row in expired_rows:
        row.status = GrantStatus.EXPIRED
        row.featured_rank = None
        row.updated_at = now
        db.add(row)
    db.flush()
    return len(expired_rows)


def get_top_10_grants(
    db: Session,
    limit: int = 10,
    reference_date: Optional[date] = None,
) -> List[Grant]:
    """Retrieve curated top published grants ordered by featured_rank then nearest deadline (D7).

    Criteria:
    - Automatically expires any published grant whose deadline < reference_date.
    - Status must be PUBLISHED.
    - Deadline must be today or in the future, or NULL (ongoing/open).
    - Ordering:
      1. Curated grants (`featured_rank IS NOT NULL`) before non-featured grants.
      2. `featured_rank ASC`
      3. `deadline ASC NULLS LAST`
      4. `updated_at DESC`
    - Limits to top 10 (or specified limit).
    """
    ref_date = reference_date or date.today()
    sync_expired_grants(db, reference_date=ref_date)
    featured_null_last = case((Grant.featured_rank.is_(None), 1), else_=0)

    query = (
        db.query(Grant)
        .filter(Grant.status == GrantStatus.PUBLISHED)
        .filter(or_(Grant.deadline.is_(None), Grant.deadline >= ref_date))
        .order_by(
            asc(featured_null_last),
            asc(Grant.featured_rank),
            nulls_last(asc(Grant.deadline)),
            desc(Grant.updated_at),
        )
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

    # Normalize Yemeni eligibility enum if passed as string, keeping consistency with nationality_rule
    nationality_rule_val = data.get("nationality_rule")
    accepts_yemeni_raw = data.get("accepts_yemeni")
    if isinstance(nationality_rule_val, dict) and nationality_rule_val.get("mode") not in (None, "unclear"):
        derived = evaluate_nationality("YE", nationality_rule_val)
        if accepts_yemeni_raw is None or str(accepts_yemeni_raw).lower() == "unclear":
            accepts_yemeni_raw = derived

    accepts_yemeni_val = accepts_yemeni_raw if accepts_yemeni_raw is not None else YemeniEligibilityStatus.UNCLEAR
    if isinstance(accepts_yemeni_val, str):
        try:
            accepts_yemeni_val = YemeniEligibilityStatus(accepts_yemeni_val.lower())
        except ValueError:
            accepts_yemeni_val = YemeniEligibilityStatus.UNCLEAR

    if "min_gpa_normalized_4" not in data and data.get("min_gpa_value") is not None:
        data["min_gpa_normalized_4"] = normalize_gpa_to_4(data.get("min_gpa_value"), data.get("min_gpa_scale"))

    structured_keys = [
        "title",
        "description",
        "eligibility",
        "criteria",
        "fields_of_study",
        "funding",
        "required_documents",
        "deadline",
        "how_to_apply",
        "featured_rank",
        "provider_name",
        "host_country",
        "allowed_degrees",
        "min_gpa_value",
        "min_gpa_scale",
        "min_gpa_normalized_4",
        "language_requirements",
        "nationality_rule",
        "min_work_years",
        "max_age",
        "funding_type",
        "evidence",
        "field_verification",
        "content_hash",
        "last_checked_at",
    ]

    if existing:
        # Update existing record
        for key in structured_keys:
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
        featured_rank=data.get("featured_rank"),
        provider_name=data.get("provider_name"),
        host_country=data.get("host_country"),
        allowed_degrees=data.get("allowed_degrees"),
        min_gpa_value=data.get("min_gpa_value"),
        min_gpa_scale=data.get("min_gpa_scale"),
        min_gpa_normalized_4=data.get("min_gpa_normalized_4"),
        language_requirements=data.get("language_requirements"),
        nationality_rule=nationality_rule_val,
        min_work_years=data.get("min_work_years"),
        max_age=data.get("max_age"),
        funding_type=data.get("funding_type"),
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


def set_featured_rank(db: Session, grant_id: int, featured_rank: Optional[int]) -> Optional[Grant]:
    """Set or clear the curated Top 10 priority (`featured_rank`, 1..10 or None) for a grant."""
    if featured_rank is not None and (featured_rank < 1 or featured_rank > 10):
        raise ValueError("featured_rank must be between 1 and 10 or null.")
    grant = get_grant_by_id(db, grant_id)
    if not grant:
        return None
    grant.featured_rank = featured_rank
    grant.updated_at = datetime.now(timezone.utc)
    db.add(grant)
    db.flush()
    return grant


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
    grant.featured_rank = None
    grant.updated_at = datetime.now(timezone.utc)
    db.add(grant)
    db.flush()
    return grant


def create_manual_grant(
    db: Session,
    data: Dict[str, Any],
    *,
    publish_immediately: bool = False,
) -> Grant:
    """Create a new grant entered manually by an administrator."""
    url = str(data.get("official_url") or "").strip()
    if not url:
        raise ValueError("official_url is required.")
    if get_grant_by_url(db, url) is not None:
        raise ValueError("DUPLICATE_URL")

    accepts_raw = str(data.get("accepts_yemeni") or "unclear").lower()
    try:
        accepts_enum = YemeniEligibilityStatus(accepts_raw)
    except ValueError:
        accepts_enum = YemeniEligibilityStatus.UNCLEAR

    min_gpa_val = data.get("min_gpa_value")
    min_gpa_scale = data.get("min_gpa_scale")
    norm_gpa = (
        normalize_gpa_to_4(min_gpa_val, min_gpa_scale)
        if min_gpa_val is not None
        else None
    )

    deadline_val = data.get("deadline")
    if isinstance(deadline_val, date) and deadline_val < date.today():
        status_val = GrantStatus.EXPIRED
    else:
        status_val = GrantStatus.PUBLISHED if publish_immediately else GrantStatus.DRAFT

    field_verification = {
        k: "admin_manual"
        for k in (
            "title",
            "official_url",
            "description",
            "eligibility",
            "criteria",
            "fields_of_study",
            "funding",
            "required_documents",
            "deadline",
            "how_to_apply",
            "accepts_yemeni",
            "provider_name",
            "host_country",
            "allowed_degrees",
            "min_gpa",
            "funding_type",
        )
        if data.get(k) not in (None, "", [])
    }
    if isinstance(data.get("evidence"), dict) and data.get("evidence"):
        for k in data["evidence"]:
            if k in field_verification:
                field_verification[k] = "verified"

    now = datetime.now(timezone.utc)
    grant = Grant(
        title=str(data.get("title") or "").strip(),
        official_url=url,
        description=data.get("description"),
        eligibility=data.get("eligibility") or None,
        criteria=data.get("criteria") or None,
        fields_of_study=data.get("fields_of_study") or None,
        funding=data.get("funding"),
        required_documents=data.get("required_documents") or None,
        deadline=deadline_val,
        how_to_apply=data.get("how_to_apply"),
        accepts_yemeni=accepts_enum,
        featured_rank=data.get("featured_rank") if status_val != GrantStatus.EXPIRED else None,
        provider_name=data.get("provider_name"),
        host_country=data.get("host_country"),
        allowed_degrees=data.get("allowed_degrees") or None,
        min_gpa_value=min_gpa_val,
        min_gpa_scale=min_gpa_scale,
        min_gpa_normalized_4=norm_gpa,
        language_requirements=data.get("language_requirements") or None,
        nationality_rule=data.get("nationality_rule"),
        min_work_years=data.get("min_work_years"),
        max_age=data.get("max_age"),
        funding_type=data.get("funding_type"),
        evidence=data.get("evidence") or {},
        field_verification=field_verification,
        status=status_val,
        created_at=now,
        updated_at=now,
    )
    db.add(grant)
    db.flush()
    return grant


def update_grant_fields(
    db: Session,
    grant_id: int,
    data: Dict[str, Any],
) -> Optional[Grant]:
    """Update editable grant fields for an existing grant."""
    grant = get_grant_by_id(db, grant_id)
    if not grant:
        return None

    if "official_url" in data and data["official_url"]:
        new_url = str(data["official_url"]).strip()
        if new_url != grant.official_url:
            existing = get_grant_by_url(db, new_url)
            if existing is not None and existing.id != grant.id:
                raise ValueError("DUPLICATE_URL")
            grant.official_url = new_url

    editable_keys = (
        "title",
        "description",
        "eligibility",
        "criteria",
        "fields_of_study",
        "funding",
        "required_documents",
        "deadline",
        "how_to_apply",
        "featured_rank",
        "provider_name",
        "host_country",
        "allowed_degrees",
        "min_gpa_value",
        "min_gpa_scale",
        "min_work_years",
        "max_age",
        "funding_type",
        "language_requirements",
        "evidence",
    )
    for key in editable_keys:
        if key in data:
            setattr(grant, key, data[key])

    if "accepts_yemeni" in data and data["accepts_yemeni"] is not None:
        try:
            grant.accepts_yemeni = YemeniEligibilityStatus(str(data["accepts_yemeni"]).lower())
        except ValueError:
            grant.accepts_yemeni = YemeniEligibilityStatus.UNCLEAR

    if "min_gpa_value" in data or "min_gpa_scale" in data:
        grant.min_gpa_normalized_4 = (
            normalize_gpa_to_4(grant.min_gpa_value, grant.min_gpa_scale)
            if grant.min_gpa_value is not None
            else None
        )

    if "status" in data and data["status"] is not None:
        try:
            grant.status = GrantStatus(str(data["status"]).lower())
        except ValueError:
            pass

    if grant.deadline is not None and grant.deadline < date.today() and grant.status == GrantStatus.PUBLISHED:
        grant.status = GrantStatus.EXPIRED
        grant.featured_rank = None

    grant.updated_at = datetime.now(timezone.utc)
    db.add(grant)
    db.flush()
    return grant


def delete_grant(db: Session, grant_id: int) -> bool:
    """Permanently delete a grant and its dependent log/plan references."""
    grant = get_grant_by_id(db, grant_id)
    if not grant:
        return False
    db.query(UpdateLog).filter(UpdateLog.grant_id == grant_id).delete(synchronize_session=False)
    db.query(PlanItem).filter(PlanItem.grant_id == grant_id).delete(synchronize_session=False)
    db.query(GrantChangeReview).filter(GrantChangeReview.grant_id == grant_id).delete(synchronize_session=False)
    db.query(DocumentDraft).filter(DocumentDraft.grant_id == grant_id).update(
        {"grant_id": None}, synchronize_session=False
    )
    db.query(Notification).filter(Notification.grant_id == grant_id).update(
        {"grant_id": None}, synchronize_session=False
    )
    db.delete(grant)
    db.flush()
    return True


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
