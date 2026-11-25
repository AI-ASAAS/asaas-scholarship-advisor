"""Pydantic request and response contracts for the Discovery Agents FastAPI boundary."""

from datetime import date
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


LLMProviderLiteral = Literal["gemini", "openai", "openrouter", "groq"]


class LanguageRequirementResponse(BaseModel):
    language: str
    test: Optional[str] = None
    min_score: Optional[float] = None
    cefr: Optional[str] = None


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
    featured_rank: Optional[int] = None
    is_featured: bool = False
    provider_name: Optional[str] = None
    host_country: Optional[str] = None
    allowed_degrees: Optional[List[str]] = None
    min_gpa_value: Optional[float] = None
    min_gpa_scale: Optional[str] = None
    min_gpa_normalized_4: Optional[float] = None
    language_requirements: Optional[List[LanguageRequirementResponse]] = None
    nationality_rule: Optional[Dict[str, Any]] = None
    min_work_years: Optional[float] = None
    max_age: Optional[int] = None
    funding_type: Optional[str] = None
    evidence: Dict[str, str] = Field(default_factory=dict)
    field_verification: Dict[str, str] = Field(default_factory=dict)
    status: Literal["draft", "published", "expired"] = "draft"
    content_hash: Optional[str] = None
    last_checked_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FeaturedRankRequest(BaseModel):
    featured_rank: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Optional priority rank (1..10) for curated Top 10 ordering, or null to unpin.",
    )


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


class ManualGrantBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=3, max_length=300)
    official_url: Optional[str] = Field(default=None, min_length=8, max_length=1000)
    description: Optional[str] = Field(default=None, max_length=4000)
    provider_name: Optional[str] = Field(default=None, max_length=200)
    host_country: Optional[str] = Field(default=None, max_length=120)
    deadline: Optional[date] = None
    funding: Optional[str] = Field(default=None, max_length=1000)
    funding_type: Optional[str] = Field(default=None, max_length=64)
    accepts_yemeni: Optional[Literal["yes", "no", "unclear"]] = None
    allowed_degrees: Optional[List[str]] = Field(default=None, max_length=10)
    fields_of_study: Optional[List[str]] = Field(default=None, max_length=30)
    eligibility: Optional[List[str]] = Field(default=None, max_length=30)
    criteria: Optional[List[str]] = Field(default=None, max_length=30)
    required_documents: Optional[List[str]] = Field(default=None, max_length=30)
    how_to_apply: Optional[str] = Field(default=None, max_length=2000)
    min_gpa_value: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    min_gpa_scale: Optional[Literal["4.0", "5.0", "100", "label"]] = None
    min_work_years: Optional[float] = Field(default=None, ge=0.0, le=50.0)
    max_age: Optional[int] = Field(default=None, ge=14, le=80)
    featured_rank: Optional[int] = Field(default=None, ge=1, le=10)
    evidence: Optional[Dict[str, str]] = None


class GrantIngestPreviewResponse(BaseModel):
    title: str
    official_url: str
    description: Optional[str] = None
    provider_name: Optional[str] = None
    host_country: Optional[str] = None
    deadline: Optional[str] = None
    funding: Optional[str] = None
    funding_type: Optional[str] = None
    accepts_yemeni: Literal["yes", "no", "unclear"] = "unclear"
    allowed_degrees: Optional[List[str]] = None
    fields_of_study: Optional[List[str]] = None
    eligibility: Optional[List[str]] = None
    criteria: Optional[List[str]] = None
    required_documents: Optional[List[str]] = None
    how_to_apply: Optional[str] = None
    min_gpa_value: Optional[float] = None
    min_gpa_scale: Optional[str] = None
    min_gpa_normalized_4: Optional[float] = None
    evidence: Dict[str, str] = Field(default_factory=dict)
    field_verification: Dict[str, str] = Field(default_factory=dict)
    already_exists_id: Optional[int] = None
    already_exists_status: Optional[Literal["draft", "published", "expired"]] = None


class ManualGrantCreateRequest(ManualGrantBase):
    title: str = Field(..., min_length=3, max_length=300)
    official_url: str = Field(..., min_length=8, max_length=1000)
    accepts_yemeni: Literal["yes", "no", "unclear"] = "unclear"
    publish_immediately: bool = False


class ManualGrantUpdateRequest(ManualGrantBase):
    status: Optional[Literal["draft", "published", "expired"]] = None


class UpdateKeysRequest(BaseModel):
    llm_provider: Optional[LLMProviderLiteral] = None
    llm_api_key: Optional[str] = Field(default=None, max_length=300)
    llm_model: Optional[str] = Field(default=None, max_length=120)
    tavily_api_key: Optional[str] = Field(default=None, max_length=300)
    serper_api_key: Optional[str] = Field(default=None, max_length=300)


class SystemStatusResponse(BaseModel):
    llm_configured: bool
    llm_provider: str = "openrouter"
    llm_model: str
    llm_models: List[str] = Field(default_factory=list)
    llm_key_hint: Optional[str] = None
    search_configured: bool
    search_provider: Optional[str] = None
    tavily_key_hint: Optional[str] = None
    serper_key_hint: Optional[str] = None
    dev_keys_enabled: bool = False
    counts: GrantCountsResponse


class FetchModelsRequest(BaseModel):
    llm_provider: LLMProviderLiteral
    llm_api_key: Optional[str] = Field(default=None, max_length=300)


class FetchModelsResponse(BaseModel):
    provider: str
    models: List[str]
    source: Literal["live", "presets"]
    note: Optional[str] = None


class KeyTestResponse(BaseModel):
    llm_ok: bool
    llm_provider: str
    llm_model: str
    llm_key_hint: Optional[str] = None
    llm_message: str
    search_configured: bool
    search_provider: Optional[str] = None
    search_message: str
