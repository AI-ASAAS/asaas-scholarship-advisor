"""Pydantic contracts for profile-aware external scholarship search (D10)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.matching.nationalities import normalize_country_code
from modules.matching.schemas import GrantMatchResult
from modules.students.schemas import DegreeLiteral, GpaScaleLiteral, StudentLanguageItem

RunStatusLiteral = Literal["complete", "partial", "failed"]


class SearchQueryPlanLLM(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: List[str] = Field(..., min_length=1, max_length=5)


class ExternalSearchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[str] = Field(default=None, max_length=64)
    nationality: str = Field(default="YE", min_length=2, max_length=60)
    target_degree: DegreeLiteral = "master"
    major: str = Field(..., min_length=2, max_length=160)
    target_countries: List[str] = Field(default_factory=list, max_length=10)
    target_fields: List[str] = Field(default_factory=list, max_length=10)
    gpa_raw: Optional[str] = Field(default=None, max_length=32)
    gpa_scale: Optional[GpaScaleLiteral] = None
    languages: List[StudentLanguageItem] = Field(default_factory=list, max_length=6)
    use_cache: bool = True
    exclude_platform_grants: bool = False
    only_eligible: bool = False
    max_results: Optional[int] = Field(default=None, ge=1, le=10)

    @field_validator("nationality")
    @classmethod
    def _norm_nat(cls, val: str) -> str:
        code = normalize_country_code(val)
        if not code:
            raise ValueError("رمز الجنسية غير صالح.")
        return code


class ExternalSearchStepLog(BaseModel):
    step_number: int
    kind: Literal["plan_queries", "search", "validate_url", "fetch_page", "extract", "cache_hit", "budget_stop"]
    target: Optional[str] = None
    verdict: Literal["ok", "rejected", "skipped", "stopped"]
    message_ar: str
    message_en: str


class ExternalSearchCandidateResult(BaseModel):
    title: str
    official_url: str
    content_hash: str
    description: Optional[str] = None
    eligibility: List[str] = Field(default_factory=list)
    criteria: List[str] = Field(default_factory=list)
    fields_of_study: List[str] = Field(default_factory=list)
    funding: Optional[str] = None
    funding_type: str = "unknown"
    required_documents: List[str] = Field(default_factory=list)
    deadline: Optional[str] = None
    how_to_apply: Optional[str] = None
    provider_name: Optional[str] = None
    host_country: Optional[str] = None
    allowed_degrees: List[str] = Field(default_factory=list)
    nationality_rule: Dict[str, Any] = Field(default_factory=dict)
    eligibility_verdict: Literal["yes", "no", "unclear"]
    nationality_evidence: Optional[str] = None
    evidence: Dict[str, str] = Field(default_factory=dict)
    field_verification: Dict[str, str] = Field(default_factory=dict)
    match_result: GrantMatchResult
    outside_platform_label_ar: str = "خارج المنصة — لم تراجعه أساس بعد"
    outside_platform_label_en: str = "Outside the platform, not reviewed by ASAAS"


class ExternalSearchMatchesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=5, ge=1, le=5)
    run_id: Optional[str] = Field(default=None, max_length=64)
    use_cache: bool = True


class ExternalSearchRunResponse(BaseModel):
    run_id: str
    status: RunStatusLiteral
    stop_reason_ar: str
    stop_reason_en: str
    cached: bool = False
    queries_executed: int
    pages_checked: int
    steps_taken: int
    tokens_used: int = 0
    elapsed_ms: int = 0
    excluded_platform_count: int = 0
    step_log: List[ExternalSearchStepLog] = Field(default_factory=list)
    results: List[ExternalSearchCandidateResult] = Field(default_factory=list)
    disclaimer_ar: str = "النتائج التالية من مواقع خارجية تم التحقق من نصوصها آلياً، ولم تعتمدها أساس للنشر بعد."
    disclaimer_en: str = "Results below come from verified external pages and have not been reviewed by ASAAS yet."


class PromoteExternalGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=2, max_length=500)
    official_url: str = Field(..., min_length=8, max_length=1000)
    description: Optional[str] = None
    eligibility: Optional[List[str]] = None
    criteria: Optional[List[str]] = None
    fields_of_study: Optional[List[str]] = None
    funding: Optional[str] = None
    required_documents: Optional[List[str]] = None
    deadline: Optional[str] = None
    how_to_apply: Optional[str] = None
    provider_name: Optional[str] = None
    host_country: Optional[str] = None
    allowed_degrees: Optional[List[str]] = None
    funding_type: Optional[str] = "unknown"
    nationality_rule: Optional[Dict[str, Any]] = None
    evidence: Dict[str, str] = Field(default_factory=dict)
    content_hash: Optional[str] = None
