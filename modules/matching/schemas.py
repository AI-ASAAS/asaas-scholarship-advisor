"""Pydantic contracts for deterministic scholarship matching and profile analysis."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

CriterionStatus = Literal["met", "not_met", "unknown", "not_applicable"]


class CriterionBreakdown(BaseModel):
    key: str
    status: CriterionStatus
    weight: int
    grant_value: Optional[str] = None
    student_value: Optional[str] = None
    evidence_quote: Optional[str] = None
    reason_ar: str
    reason_en: str


class DisqualifierItem(BaseModel):
    gate: str
    reason_ar: str
    reason_en: str
    evidence_quote: Optional[str] = None


class GrantMatchResult(BaseModel):
    grant_id: int
    title: str
    official_url: str
    deadline: Optional[str] = None
    host_country: Optional[str] = None
    funding_type: Optional[str] = None
    featured_rank: Optional[int] = None
    accepts_yemeni: Literal["yes", "no", "unclear"] = "unclear"
    nationality_rule: Optional[Dict[str, Any]] = None
    eligible: bool
    status: Literal["eligible", "ineligible"]
    disqualifiers: List[DisqualifierItem] = Field(default_factory=list)
    match_percentage: float
    coverage_percentage: float
    weights_version: str
    criteria: List[CriterionBreakdown] = Field(default_factory=list)
    missing_info_hints: List[str] = Field(default_factory=list)


class MatchesListResponse(BaseModel):
    eligible_grants: List[GrantMatchResult]
    ineligible_grants: List[GrantMatchResult]
    total_evaluated: int
    weights_version: str
    gpa_scales_version: str
    disclaimer_ar: str
    disclaimer_en: str


class DeterministicFinding(BaseModel):
    id: str
    kind: Literal["strength", "weakness", "gap", "documents"]
    summary_ar: str
    summary_en: str
    count: int = 0
    related_grants: List[str] = Field(default_factory=list)


class AnalysisStatement(BaseModel):
    text_ar: str = Field(..., min_length=4, max_length=320)
    finding_ids: List[str] = Field(..., min_length=1)


class LLMProfileAnalysisNarrative(BaseModel):
    summary_ar: str = Field(..., min_length=8, max_length=600)
    strengths: List[AnalysisStatement] = Field(default_factory=list)
    weaknesses: List[AnalysisStatement] = Field(default_factory=list)
    improvement_areas: List[AnalysisStatement] = Field(default_factory=list)


class ProfileAnalysisResponse(BaseModel):
    analysis_mode: Literal["llm_grounded", "deterministic_fallback"]
    prompt_version: Optional[str] = None
    retryable: bool = False
    fallback_notice_ar: Optional[str] = None
    fallback_notice_en: Optional[str] = None
    findings: List[DeterministicFinding]
    summary_ar: str
    strengths: List[AnalysisStatement]
    weaknesses: List[AnalysisStatement]
    improvement_areas: List[AnalysisStatement]
    dropped_ungrounded_count: int = 0
