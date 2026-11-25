"""Business logic for student identity lifecycle, consent verification, and PII-safe export/deletion."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.db import get_db
from modules.matching.gpa import normalize_student_gpa
from modules.students.repository import StudentProfileRecord, StudentRepository
from modules.students.schemas import (
    CURRENT_CONSENT_VERSION,
    StudentDeleteResponse,
    StudentExportResponse,
    StudentLanguageItem,
    StudentProfileResponse,
    StudentProfileUpsertRequest,
)

# Defensive PII scrubber before any student note leaves the backend toward a model
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s\-()]{6,}\d)")


class ConsentRequiredError(Exception):
    """Raised when attempting to persist a profile without active explicit consent."""


def scrub_pii_notes(notes: List[str]) -> List[str]:
    """Strip accidental emails or phone numbers from optional achievement/experience notes."""
    cleaned: List[str] = []
    for note in notes:
        s = _EMAIL_RE.sub("[redacted-email]", note)
        s = _PHONE_RE.sub("[redacted-phone]", s)
        cleaned.append(s)
    return cleaned


def _to_profile_response(
    record: StudentProfileRecord,
    consent: Optional[Dict[str, Any]],
) -> StudentProfileResponse:
    _, is_assumed_label = normalize_student_gpa(record["gpa_raw"], record["gpa_scale"])
    langs = [StudentLanguageItem(**item) for item in record.get("languages", [])]
    return StudentProfileResponse(
        nationality=record["nationality"],
        country_of_residence=record["country_of_residence"],
        current_degree=record["current_degree"],  # type: ignore[arg-type]
        expected_graduation_year=record["expected_graduation_year"],
        target_degree=record["target_degree"],  # type: ignore[arg-type]
        major=record["major"],
        gpa_raw=record["gpa_raw"],
        gpa_scale=record["gpa_scale"],  # type: ignore[arg-type]
        gpa_normalized_4=record["gpa_normalized_4"],
        gpa_label_assumed=is_assumed_label,
        languages=langs,
        target_countries=record["target_countries"],
        target_fields=record["target_fields"],
        funding_need=record["funding_need"],  # type: ignore[arg-type]
        work_experience_years=record["work_experience_years"],
        experience_notes=record["experience_notes"],
        age_years=record["age_years"],
        publications_count=record["publications_count"],
        has_consent=consent is not None,
        consent_version=consent["consent_version"] if consent else None,
        updated_at=record["updated_at"],
    )


class StudentService:
    """Orchestrates student consent, profile persistence, export, and deletion."""

    def get_status(self, session_id: Optional[str]) -> Dict[str, Any]:
        if not session_id:
            return {
                "authenticated": False,
                "has_consent": False,
                "consent_version": None,
                "profile_exists": False,
            }
        with get_db() as db:
            consent = StudentRepository.get_active_consent(db, session_id)
            profile = StudentRepository.get_profile(db, session_id)
            return {
                "authenticated": True,
                "has_consent": consent is not None,
                "consent_version": consent["consent_version"] if consent else None,
                "profile_exists": profile is not None,
            }

    def record_consent(
        self,
        session_id: str,
        consent_version: str = CURRENT_CONSENT_VERSION,
        scopes: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        default_scopes = {"profile_storage": True, "ai_processing": True, "in_app_alerts": True}
        with get_db() as db:
            return StudentRepository.record_consent(
                db,
                session_id=session_id,
                consent_version=consent_version,
                scopes=scopes or default_scopes,
            )

    def get_profile(self, session_id: str) -> Optional[StudentProfileResponse]:
        with get_db() as db:
            record = StudentRepository.get_profile(db, session_id)
            if record is None:
                return None
            consent = StudentRepository.get_active_consent(db, session_id)
            return _to_profile_response(record, consent)

    def save_profile(
        self,
        session_id: str,
        payload: StudentProfileUpsertRequest,
    ) -> StudentProfileResponse:
        gpa_4, _ = normalize_student_gpa(payload.gpa_raw, payload.gpa_scale)

        with get_db() as db:
            active_consent = StudentRepository.get_active_consent(db, session_id)
            if active_consent is None:
                if payload.consent_accepted is True:
                    active_consent = StudentRepository.record_consent(
                        db,
                        session_id=session_id,
                        consent_version=payload.consent_version or CURRENT_CONSENT_VERSION,
                        scopes={"profile_storage": True, "ai_processing": True, "in_app_alerts": True},
                    )
                else:
                    raise ConsentRequiredError(
                        "الموافقة الصريحة على الخصوصية مطلوبة قبل حفظ الملف الشخصي."
                    )

            record = StudentRepository.upsert_profile(
                db,
                session_id=session_id,
                payload={
                    "nationality": payload.nationality,
                    "country_of_residence": payload.country_of_residence,
                    "current_degree": payload.current_degree,
                    "expected_graduation_year": payload.expected_graduation_year,
                    "target_degree": payload.target_degree,
                    "major": payload.major,
                    "gpa_raw": payload.gpa_raw,
                    "gpa_scale": payload.gpa_scale,
                    "gpa_normalized_4": gpa_4,
                    "languages": [item.model_dump() for item in payload.languages],
                    "target_countries": payload.target_countries,
                    "target_fields": payload.target_fields,
                    "funding_need": payload.funding_need,
                    "work_experience_years": payload.work_experience_years,
                    "experience_notes": scrub_pii_notes(payload.experience_notes),
                    "age_years": payload.age_years,
                    "publications_count": payload.publications_count,
                },
            )
            return _to_profile_response(record, active_consent)

    def export_data(self, session_id: str) -> StudentExportResponse:
        with get_db() as db:
            consents = StudentRepository.list_consents(db, session_id)
            active = StudentRepository.get_active_consent(db, session_id)
            record = StudentRepository.get_profile(db, session_id)
            related = StudentRepository.count_optional_related_records(db, session_id)
            return StudentExportResponse(
                exported_at=datetime.now(timezone.utc).isoformat(),
                consent_records=consents,
                profile=_to_profile_response(record, active) if record else None,
                related_records=related,
            )

    def delete_data(self, session_id: str) -> StudentDeleteResponse:
        with get_db() as db:
            removed = StudentRepository.delete_all_session_data(db, session_id)
            return StudentDeleteResponse(deleted=True, removed_counts=removed)
