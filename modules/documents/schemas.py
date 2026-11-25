"""Pydantic contracts for profile strengthening and application document help (D9)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.config import settings

DocTypeLiteral = Literal["cv", "motivation_letter", "recommendation_support", "certificates"]
DocLangLiteral = Literal["ar", "en"]
ClaimStatusLiteral = Literal["needs_confirmation", "accepted", "removed"]


class StrengtheningGap(BaseModel):
    gap_id: str
    gap_type: Literal["language", "gpa", "documents", "deadline_proximity", "experience", "other"]
    severity: Literal["high", "medium", "low"]
    title_ar: str
    title_en: str
    evidence_ar: str
    evidence_en: str
    related_grants: List[str] = Field(default_factory=list)
    is_assumption: bool = False
    assumption_note_ar: Optional[str] = None
    assumption_note_en: Optional[str] = None


class StrengtheningActionItem(BaseModel):
    gap_id: str
    what_ar: str
    why_ar: str
    next_step_ar: str
    is_assumption: bool = False


class LLMStrengtheningAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str
    what_ar: str
    why_ar: str
    next_step_ar: str


class LLMStrengtheningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_ar: str
    actions: List[LLMStrengtheningAction] = Field(default_factory=list)


class StrengtheningDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: DocTypeLiteral
    filename: Optional[str] = Field(default=None, max_length=255)
    content: str = Field(..., min_length=10, max_length=8000)


class StrengtheningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_ids: Optional[List[int]] = Field(default=None, max_length=10)
    documents: Optional[List[StrengtheningDocumentInput]] = Field(default=None, max_length=4)


class DocumentExtractFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: DocTypeLiteral
    filename: str = Field(..., min_length=1, max_length=255)
    content_base64: str = Field(..., min_length=4, max_length=3_000_000)


class DocumentExtractFileResponse(BaseModel):
    doc_type: DocTypeLiteral
    filename: str
    extracted_text: str
    char_count: int
    truncated: bool = False


class StrengtheningResponse(BaseModel):
    gaps: List[StrengtheningGap] = Field(default_factory=list)
    summary_ar: str
    actions: List[StrengtheningActionItem] = Field(default_factory=list)
    prompt_version: Optional[str] = None
    used_fallback: bool = False
    disclaimer_ar: str
    disclaimer_en: str


class LedgerEntry(BaseModel):
    id: str
    source: Literal["profile", "pasted_text", "grant"]
    category: str
    value: str
    normalized_tokens: List[str] = Field(default_factory=list)


class DocumentClaim(BaseModel):
    text: str
    category: Literal["number", "date", "gpa", "language_score", "institution", "employer", "award", "other"]
    ledger_id: Optional[str] = None


class FlaggedClaim(BaseModel):
    id: str
    claim_text: str
    category: Literal[
        "number",
        "date",
        "gpa",
        "language_score",
        "institution",
        "employer",
        "award",
        "conflict",
        "recommendation_voice",
        "other",
    ]
    reason_ar: str
    reason_en: str
    status: ClaimStatusLiteral = "needs_confirmation"


class DocumentSection(BaseModel):
    title: str
    content: str


class DocumentGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: Optional[int] = Field(default=None, ge=1)
    doc_type: DocTypeLiteral
    language: DocLangLiteral = "ar"
    source_text: str = Field(..., min_length=10)
    target_instructions: Optional[str] = Field(default=None, max_length=500)

    @field_validator("source_text")
    @classmethod
    def _enforce_max_chars(cls, val: str) -> str:
        cleaned = (val or "").strip()
        if len(cleaned) < 10:
            raise ValueError("يرجى لصق نص تعريفي أو مسودة أولية لا تقل عن 10 أحرف.")
        if len(cleaned) > settings.DOCUMENTS_MAX_INPUT_CHARS:
            raise ValueError(
                f"الحد الأقصى للنص المُدخل هو {settings.DOCUMENTS_MAX_INPUT_CHARS} حرف."
            )
        return cleaned


class LLMDocumentDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_text: str = Field(..., min_length=20)
    sections: List[DocumentSection] = Field(default_factory=list)
    claims: List[DocumentClaim] = Field(default_factory=list)
    missing_info_requests: List[str] = Field(default_factory=list)


class DocumentGenerateResponse(BaseModel):
    grant_id: Optional[int] = None
    grant_title: Optional[str] = None
    doc_type: DocTypeLiteral
    language: DocLangLiteral
    draft_text: str
    sections: List[DocumentSection] = Field(default_factory=list)
    facts_ledger: List[LedgerEntry] = Field(default_factory=list)
    claims: List[DocumentClaim] = Field(default_factory=list)
    flagged_claims: List[FlaggedClaim] = Field(default_factory=list)
    conflicts: List[FlaggedClaim] = Field(default_factory=list)
    missing_info_requests: List[str] = Field(default_factory=list)
    prompt_version: str
    responsibility_note_ar: str
    responsibility_note_en: str


class DocumentSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: Optional[int] = Field(default=None, ge=1)
    doc_type: DocTypeLiteral
    language: DocLangLiteral = "ar"
    source_text: Optional[str] = Field(default=None, max_length=settings.DOCUMENTS_MAX_INPUT_CHARS)
    draft_text: str = Field(..., min_length=10, max_length=20000)
    facts_ledger: List[LedgerEntry] = Field(default_factory=list, max_length=200)
    flagged_claims: List[FlaggedClaim] = Field(default_factory=list, max_length=200)
    prompt_version: Optional[str] = Field(default="documents@1.0", max_length=64)


class DocumentDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_text: Optional[str] = Field(default=None, min_length=10, max_length=20000)
    flagged_claims: Optional[List[FlaggedClaim]] = Field(default=None, max_length=200)


class SavedDocumentDraftResponse(BaseModel):
    id: int
    grant_id: Optional[int] = None
    grant_title: Optional[str] = None
    doc_type: DocTypeLiteral
    language: DocLangLiteral
    draft_text: str
    facts_ledger: List[LedgerEntry] = Field(default_factory=list)
    flagged_claims: List[FlaggedClaim] = Field(default_factory=list)
    prompt_version: Optional[str] = None
    created_at: str
    updated_at: str


class SavedDocumentListResponse(BaseModel):
    count: int
    drafts: List[SavedDocumentDraftResponse] = Field(default_factory=list)
