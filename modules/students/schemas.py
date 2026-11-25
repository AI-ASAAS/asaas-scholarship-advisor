"""Pydantic schemas for the student identity, consent, and profile API boundary."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.matching.gpa import normalize_student_gpa
from modules.matching.nationalities import normalize_country_code

CURRENT_CONSENT_VERSION = "privacy-v1"
DegreeLiteral = Literal["high_school", "bachelor", "master", "phd"]
GpaScaleLiteral = Literal["4.0", "5.0", "100", "label"]
FundingNeedLiteral = Literal["full", "partial", "any"]
CefrLiteral = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class StudentLanguageItem(BaseModel):
    """Language qualification or self-assessed level."""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(..., min_length=2, max_length=60)
    test_name: Optional[str] = Field(default=None, max_length=40)
    score: Optional[float] = Field(default=None, ge=0.0, le=990.0)
    self_assessed_cefr: Optional[CefrLiteral] = None
    is_self_assessed: bool = False

    @model_validator(mode="after")
    def _enforce_self_assessed_flag(self) -> "StudentLanguageItem":
        has_official = bool(self.test_name and self.test_name.strip()) and self.score is not None
        if not has_official:
            self.is_self_assessed = True
            if self.test_name is not None and not self.test_name.strip():
                self.test_name = None
        else:
            self.test_name = self.test_name.strip().upper()  # type: ignore[union-attr]
        self.language = self.language.strip()
        return self


class ConsentRecordRequest(BaseModel):
    """Explicit consent payload (must accept privacy policy before storing profile)."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool = True
    consent_version: str = Field(default=CURRENT_CONSENT_VERSION, min_length=3, max_length=32)
    scopes: Dict[str, bool] = Field(
        default_factory=lambda: {
            "profile_storage": True,
            "ai_processing": True,
            "in_app_alerts": True,
        }
    )

    @field_validator("accepted")
    @classmethod
    def _must_be_true(cls, val: bool) -> bool:
        if not val:
            raise ValueError("يجب الموافقة الصريحة على سياسة الخصوصية لحفظ الملف.")
        return val


class StudentSessionStartRequest(BaseModel):
    """Optional consent info when explicitly starting a student session."""

    model_config = ConfigDict(extra="forbid")

    consent_accepted: bool = False
    consent_version: str = Field(default=CURRENT_CONSENT_VERSION, min_length=3, max_length=32)
    scopes: Optional[Dict[str, bool]] = None


class StudentSessionStatusResponse(BaseModel):
    authenticated: bool
    has_consent: bool
    consent_version: Optional[str] = None
    profile_exists: bool = False


class StudentProfileUpsertRequest(BaseModel):
    """Validated student profile input (no name, email, phone, or national ID accepted)."""

    model_config = ConfigDict(extra="forbid")

    nationality: str = Field(default="YE", min_length=2, max_length=60)
    country_of_residence: Optional[str] = Field(default=None, max_length=60)
    current_degree: Optional[DegreeLiteral] = None
    expected_graduation_year: Optional[int] = Field(default=None, ge=1990, le=2040)
    target_degree: DegreeLiteral
    major: Optional[str] = Field(default=None, max_length=160)
    gpa_raw: Optional[str] = Field(default=None, max_length=32)
    gpa_scale: Optional[GpaScaleLiteral] = None
    languages: List[StudentLanguageItem] = Field(default_factory=list, max_length=10)
    target_countries: List[str] = Field(default_factory=list, max_length=20)
    target_fields: List[str] = Field(default_factory=list, max_length=20)
    funding_need: Optional[FundingNeedLiteral] = None
    work_experience_years: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    experience_notes: List[str] = Field(default_factory=list, max_length=10)
    age_years: Optional[int] = Field(default=None, ge=14, le=80)
    publications_count: int = Field(default=0, ge=0, le=500)
    consent_accepted: Optional[bool] = None
    consent_version: str = Field(default=CURRENT_CONSENT_VERSION, min_length=3, max_length=32)

    @field_validator("nationality")
    @classmethod
    def _validate_nationality(cls, value: str) -> str:
        norm = normalize_country_code(value)
        if not norm:
            raise ValueError("رمز الجنسية غير صالح؛ استخدم رمز الدولة المكوّن من حرفين (مثل YE).")
        return norm

    @field_validator("country_of_residence")
    @classmethod
    def _validate_residence(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        norm = normalize_country_code(value)
        if not norm:
            raise ValueError("رمز بلد الإقامة غير صالح؛ استخدم رمز الدولة المكوّن من حرفين.")
        return norm

    @field_validator("major")
    @classmethod
    def _clean_major(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("experience_notes")
    @classmethod
    def _clean_notes(cls, notes: List[str]) -> List[str]:
        cleaned: List[str] = []
        for item in notes:
            s = str(item or "").strip()
            if s:
                cleaned.append(s[:240])
        return cleaned

    @field_validator("target_countries", "target_fields")
    @classmethod
    def _clean_string_lists(cls, items: List[str]) -> List[str]:
        return [str(x).strip()[:80] for x in items if str(x).strip()]

    @model_validator(mode="after")
    def _validate_gpa_pair(self) -> "StudentProfileUpsertRequest":
        normalize_student_gpa(self.gpa_raw, self.gpa_scale)
        return self


class StudentProfileResponse(BaseModel):
    nationality: str
    country_of_residence: Optional[str] = None
    current_degree: Optional[DegreeLiteral] = None
    expected_graduation_year: Optional[int] = None
    target_degree: Optional[DegreeLiteral] = None
    major: Optional[str] = None
    gpa_raw: Optional[str] = None
    gpa_scale: Optional[GpaScaleLiteral] = None
    gpa_normalized_4: Optional[float] = None
    gpa_label_assumed: bool = False
    languages: List[StudentLanguageItem] = Field(default_factory=list)
    target_countries: List[str] = Field(default_factory=list)
    target_fields: List[str] = Field(default_factory=list)
    funding_need: Optional[FundingNeedLiteral] = None
    work_experience_years: Optional[float] = None
    experience_notes: List[str] = Field(default_factory=list)
    age_years: Optional[int] = None
    publications_count: int = 0
    has_consent: bool = False
    consent_version: Optional[str] = None
    updated_at: Optional[str] = None


class StudentExportResponse(BaseModel):
    exported_at: str
    consent_records: List[Dict[str, Any]]
    profile: Optional[StudentProfileResponse] = None
    related_records: Dict[str, int] = Field(default_factory=dict)


class StudentDeleteResponse(BaseModel):
    deleted: bool
    removed_counts: Dict[str, int]
