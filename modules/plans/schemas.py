"""Pydantic contracts for the personalized application plan HTTP boundary."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

ChecklistStatusLiteral = Literal["todo", "in_progress", "done"]
PlanItemStatusLiteral = Literal["planned", "in_progress", "submitted", "archived"]
UrgencyStatusLiteral = Literal["overdue", "due_today", "due_soon", "upcoming", "no_deadline"]


class PlanAddGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: int = Field(..., ge=1)
    allow_ineligible: bool = False
    notes: Optional[str] = Field(default=None, max_length=2000)


class PlanChecklistPatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=80)
    status: ChecklistStatusLiteral


class PlanUpdateItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[PlanItemStatusLiteral] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    checklist_updates: Optional[List[PlanChecklistPatchItem]] = Field(default=None, max_length=60)


class PlanChecklistItem(BaseModel):
    id: str
    category: Literal["document", "application_step", "gap", "missing_official"]
    label_ar: str
    label_en: str
    detail_ar: Optional[str] = None
    detail_en: Optional[str] = None
    evidence_quote: Optional[str] = None
    official_url: Optional[str] = None
    is_not_stated_officially: bool = False
    is_assumption: bool = False
    status: ChecklistStatusLiteral = "todo"


class PlanMilestone(BaseModel):
    offset_days: int
    due_date: str
    days_from_today: int
    status: Literal["overdue", "due_today", "due_soon", "upcoming"]
    label_ar: str
    label_en: str
    pacing_note_ar: str
    pacing_note_en: str


class DeadlineConflict(BaseModel):
    conflict_id: str
    start_date: str
    end_date: str
    span_days: int
    grant_ids: List[int]
    grant_titles: List[str]
    message_ar: str
    message_en: str


class PlanGrantItemResponse(BaseModel):
    id: int
    grant_id: int
    title: str
    official_url: str
    host_country: Optional[str] = None
    funding_type: Optional[str] = None
    priority_rank: int
    status: PlanItemStatusLiteral
    eligible: bool
    ineligible_warning_ar: Optional[str] = None
    ineligible_warning_en: Optional[str] = None
    match_percentage: float
    coverage_percentage: float
    deadline: Optional[str] = None
    days_remaining: Optional[int] = None
    urgency: UrgencyStatusLiteral
    progress_percentage: float
    how_to_apply_text: Optional[str] = None
    how_to_apply_evidence: Optional[str] = None
    checklist: List[PlanChecklistItem] = Field(default_factory=list)
    milestones: List[PlanMilestone] = Field(default_factory=list)
    notes: Optional[str] = None


class LLMPlanSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_ar: str = Field(..., min_length=10, max_length=600)
    referenced_item_ids: List[int] = Field(default_factory=list)


class PlanSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanSummaryResponse(BaseModel):
    summary_ar: Optional[str] = None
    referenced_item_ids: List[int] = Field(default_factory=list)
    prompt_version: Optional[str] = None
    available: bool = False


class PlanOverviewResponse(BaseModel):
    plan_id: Optional[int] = None
    timezone: str
    as_of_date: str
    total_grants: int
    overall_progress_percentage: float
    conflicts: List[DeadlineConflict] = Field(default_factory=list)
    items: List[PlanGrantItemResponse] = Field(default_factory=list)
    ai_summary: Optional[PlanSummaryResponse] = None
