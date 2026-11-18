"""Pydantic request and response contracts for the Discovery Agents FastAPI boundary."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class GrantResponse(BaseModel):
    id: int
    title: str
    official_url: str
    description: Optional[str] = None
    eligibility: Optional[List[str]] = None
    criteria: Optional[List[str]] = None
    fields_of_study: Optional[List[str]] = None
    funding: Optional[str] = None
    required_documents: Optional[List[str]] = None
    deadline: Optional[str] = None
    how_to_apply: Optional[str] = None
    accepts_yemeni: Literal["yes", "no", "unclear"] = "unclear"
    evidence: Dict[str, str] = Field(default_factory=dict)
    field_verification: Dict[str, str] = Field(default_factory=dict)
    status: Literal["draft", "published", "expired"] = "draft"
    content_hash: Optional[str] = None
    last_checked_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class GrantCountsResponse(BaseModel):
    total: int
    published: int
    draft: int
    expired: int
    update_logs: int


class GrantListResponse(BaseModel):
    grants: List[GrantResponse]
    counts: GrantCountsResponse


class IngestRequest(BaseModel):
    official_url: str = Field(..., min_length=8, max_length=1000)


class ExternalSearchRequest(BaseModel):
    major: str = Field(..., min_length=2, max_length=120)
    degree_level: str = Field(..., min_length=2, max_length=60)
    target_country: Optional[str] = Field(default=None, max_length=80)
    max_steps: int = Field(default=5, ge=1, le=5)


class UpdateLogResponse(BaseModel):
    id: int
    grant_id: int
    grant_title: Optional[str] = None
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    detected_at: Optional[str] = None
    notified: bool = False


class TelegramProcessRequest(BaseModel):
    posts: List[str] = Field(..., min_length=1, max_length=30)
    dry_run: bool = Field(
        default=False,
        description="If true, only extracts, filters official domains, and deduplicates without calling LLM ingest.",
    )


class SystemStatusResponse(BaseModel):
    llm_configured: bool
    llm_model: str
    search_configured: bool
    search_provider: Optional[str] = None
    telegram_configured: bool
    counts: GrantCountsResponse
