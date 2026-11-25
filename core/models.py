"""Database models for Discovery Agents.

Implements the Unified Grant Schema, GrantStatus enum, and UpdateLog.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Enum as SAEnum,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class GrantStatus(str, Enum):
    """Lifecycle status of a scholarship entry."""
    DRAFT = "draft"
    PUBLISHED = "published"
    EXPIRED = "expired"


class YemeniEligibilityStatus(str, Enum):
    """Explicit eligibility status for Yemeni students."""
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


class Grant(Base):
    """Unified Scholarship (Grant) Model."""

    __tablename__ = "grants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    official_url = Column(String(1000), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

    # Structured list attributes (stored as JSON)
    eligibility = Column(JSON, nullable=True)  # List[str]
    criteria = Column(JSON, nullable=True)  # List[str]
    fields_of_study = Column(JSON, nullable=True)  # List[str]
    funding = Column(Text, nullable=True)
    required_documents = Column(JSON, nullable=True)  # List[str]

    # Application details
    deadline = Column(Date, nullable=True, index=True)
    how_to_apply = Column(Text, nullable=True)

    # Yemeni student specificity (preserved for backward compatibility)
    accepts_yemeni = Column(
        SAEnum(YemeniEligibilityStatus, name="yemeni_eligibility_status"),
        nullable=False,
        default=YemeniEligibilityStatus.UNCLEAR,
    )

    # Phase 2 structured eligibility & Top 10 curation
    featured_rank = Column(Integer, nullable=True)
    provider_name = Column(String(255), nullable=True)
    host_country = Column(String(64), nullable=True)
    allowed_degrees = Column(JSON, nullable=True)  # List["high_school" | "bachelor" | "master" | "phd"]
    min_gpa_value = Column(Float, nullable=True)
    min_gpa_scale = Column(String(20), nullable=True)  # "4.0" | "5.0" | "100" | "label"
    min_gpa_normalized_4 = Column(Float, nullable=True)
    language_requirements = Column(JSON, nullable=True)  # List[{"language", "test", "min_score", "cefr"}]
    nationality_rule = Column(JSON, nullable=True)  # {"mode", "countries", "groups", "evidence"}
    min_work_years = Column(Float, nullable=True)
    max_age = Column(Integer, nullable=True)
    funding_type = Column(String(32), nullable=True)  # "full" | "partial" | "tuition_only" | "stipend" | "unknown"

    # Anti-hallucination verification fields
    evidence = Column(JSON, nullable=False, default=dict)  # Dict[field_name, exact_quote]
    field_verification = Column(JSON, nullable=False, default=dict)  # Dict[field_name, "verified"|"unverified"]

    # Lifecycle and monitoring
    status = Column(
        SAEnum(GrantStatus, name="grant_status"),
        nullable=False,
        default=GrantStatus.DRAFT,
        index=True,
    )
    content_hash = Column(String(64), nullable=True)
    last_checked_at = Column(DateTime, nullable=True)

    # Timestamps (stored in UTC)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    update_logs = relationship("UpdateLog", back_populates="grant", cascade="all, delete-orphan")

    # Composite indexes for rapid curated/deadline Top 10 queries
    __table_args__ = (
        Index("ix_grants_status_deadline", "status", "deadline"),
        Index("ix_grants_status_featured_deadline", "status", "featured_rank", "deadline"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize grant object to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "official_url": self.official_url,
            "description": self.description,
            "eligibility": self.eligibility,
            "criteria": self.criteria,
            "fields_of_study": self.fields_of_study,
            "funding": self.funding,
            "required_documents": self.required_documents,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "how_to_apply": self.how_to_apply,
            "accepts_yemeni": self.accepts_yemeni.value if isinstance(self.accepts_yemeni, YemeniEligibilityStatus) else self.accepts_yemeni,
            "featured_rank": self.featured_rank,
            "is_featured": self.featured_rank is not None,
            "provider_name": self.provider_name,
            "host_country": self.host_country,
            "allowed_degrees": self.allowed_degrees,
            "min_gpa_value": self.min_gpa_value,
            "min_gpa_scale": self.min_gpa_scale,
            "min_gpa_normalized_4": self.min_gpa_normalized_4,
            "language_requirements": self.language_requirements,
            "nationality_rule": self.nationality_rule,
            "min_work_years": self.min_work_years,
            "max_age": self.max_age,
            "funding_type": self.funding_type,
            "evidence": self.evidence or {},
            "field_verification": self.field_verification or {},
            "status": self.status.value if isinstance(self.status, GrantStatus) else self.status,
            "content_hash": self.content_hash,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UpdateLog(Base):
    """Audit log for tracked field changes discovered by the monitor agent."""

    __tablename__ = "update_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    grant_id = Column(Integer, ForeignKey("grants.id", ondelete="CASCADE"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    detected_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    notified = Column(Boolean, nullable=False, default=False)

    grant = relationship("Grant", back_populates="update_logs")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize log to dictionary."""
        return {
            "id": self.id,
            "grant_id": self.grant_id,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "notified": self.notified,
        }


class StudentSession(Base):
    """Anonymous server-side student session keyed by SHA-256 cookie token hash (D4)."""

    __tablename__ = "student_sessions"

    id = Column(String(36), primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime, nullable=False, index=True, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)

    consents = relationship("StudentConsent", back_populates="session", cascade="all, delete-orphan")
    profile = relationship("StudentProfile", back_populates="session", uselist=False, cascade="all, delete-orphan")


class StudentConsent(Base):
    """Explicit student privacy consent ledger (D12)."""

    __tablename__ = "student_consents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("student_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    consent_version = Column(String(32), nullable=False)
    scopes_json = Column(JSON, nullable=False, default=dict)
    accepted_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime, nullable=True)

    session = relationship("StudentSession", back_populates="consents")


class StudentProfile(Base):
    """Minimized academic student profile (no name, email, phone, or national ID)."""

    __tablename__ = "student_profiles"

    session_id = Column(String(36), ForeignKey("student_sessions.id", ondelete="CASCADE"), primary_key=True)
    nationality = Column(String(8), nullable=False, default="YE")
    country_of_residence = Column(String(8), nullable=True)
    current_degree = Column(String(24), nullable=True)
    expected_graduation_year = Column(Integer, nullable=True)
    target_degree = Column(String(24), nullable=True)
    major = Column(String(160), nullable=True)
    gpa_raw = Column(String(32), nullable=True)
    gpa_scale = Column(String(20), nullable=True)
    gpa_normalized_4 = Column(Float, nullable=True)
    languages_json = Column(JSON, nullable=False, default=list)
    target_countries_json = Column(JSON, nullable=False, default=list)
    target_fields_json = Column(JSON, nullable=False, default=list)
    funding_need = Column(String(32), nullable=True)
    work_experience_years = Column(Float, nullable=True)
    experience_notes = Column(JSON, nullable=False, default=list)
    age_years = Column(Integer, nullable=True)
    publications_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    session = relationship("StudentSession", back_populates="profile")


class Conversation(Base):
    """Scoped scholarship advisor conversation thread per student session (D8)."""

    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("student_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")


class ChatMessage(Base):
    """Individual advisor chat turn subject to 30-day retention (D12)."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    attachments_json = Column(JSON, nullable=False, default=list)
    prompt_version = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, index=True, default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="messages")


class DocumentDraft(Base):
    """Saved application document draft + facts ledger verification per student session (D9, D12)."""

    __tablename__ = "document_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("student_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    grant_id = Column(Integer, ForeignKey("grants.id", ondelete="SET NULL"), nullable=True)
    doc_type = Column(String(32), nullable=False)
    language = Column(String(8), nullable=False, default="ar")
    facts_ledger_json = Column(JSON, nullable=False, default=list)
    draft_text = Column(Text, nullable=False)
    flagged_claims_json = Column(JSON, nullable=False, default=list)
    prompt_version = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, index=True, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ApplicationPlan(Base):
    """Student-owned application plan container tied strictly to student_session_id."""

    __tablename__ = "application_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String(36),
        ForeignKey("student_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    items = relationship("PlanItem", back_populates="plan", cascade="all, delete-orphan")


class PlanItem(Base):
    """Individual pursued grant inside an application plan with checklist and private notes."""

    __tablename__ = "plan_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("application_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    grant_id = Column(Integer, ForeignKey("grants.id", ondelete="CASCADE"), nullable=False)
    priority_rank = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="planned")
    deadline_snapshot = Column(Date, nullable=True)
    checklist_json = Column(JSON, nullable=False, default=list)
    notes = Column(Text, nullable=True)
    allow_ineligible = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    plan = relationship("ApplicationPlan", back_populates="items")


class Notification(Base):
    """Deduplicated in-app notification for a student session (D11)."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String(36),
        ForeignKey("student_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_id = Column(Integer, ForeignKey("grants.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(48), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    official_url = Column(String(1000), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    dedupe_key = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, index=True, default=lambda: datetime.now(timezone.utc))


class ExternalSearchCache(Base):
    """TTL cache for verified external search runs and page extractions (D10)."""

    __tablename__ = "external_search_cache"

    query_hash = Column(String(64), primary_key=True)
    results_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False, index=True)


class GrantChangeReview(Base):
    """Admin review queue item created when monitor detects a change on an official page."""

    __tablename__ = "grant_change_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    grant_id = Column(Integer, ForeignKey("grants.id", ondelete="CASCADE"), nullable=False)
    update_log_id = Column(Integer, ForeignKey("update_logs.id", ondelete="SET NULL"), nullable=True)
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    summary_ar = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="pending", index=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
