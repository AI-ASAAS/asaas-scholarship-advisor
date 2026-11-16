"""Database models for Discovery Agents.

Implements the Unified Grant Schema, GrantStatus enum, and UpdateLog.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Boolean,
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

    # Yemeni student specificity
    accepts_yemeni = Column(
        SAEnum(YemeniEligibilityStatus, name="yemeni_eligibility_status"),
        nullable=False,
        default=YemeniEligibilityStatus.UNCLEAR,
    )

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

    # Composite index for rapid top-10 queries: published grants ordered by deadline
    __table_args__ = (
        Index("ix_grants_status_deadline", "status", "deadline"),
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
