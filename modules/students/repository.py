"""Repository layer for student sessions, consents, profiles, export, and atomic deletion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from core.models import StudentConsent, StudentProfile, StudentSession

# Child tables added in later phases (cleaned atomically whenever present).
_OPTIONAL_SESSION_TABLES = (
    "notifications",
    "document_drafts",
    "application_plans",
    "conversations",
)


class StudentProfileRecord(TypedDict):
    session_id: str
    nationality: str
    country_of_residence: Optional[str]
    current_degree: Optional[str]
    expected_graduation_year: Optional[int]
    target_degree: Optional[str]
    major: Optional[str]
    gpa_raw: Optional[str]
    gpa_scale: Optional[str]
    gpa_normalized_4: Optional[float]
    languages: List[Dict[str, Any]]
    target_countries: List[str]
    target_fields: List[str]
    funding_need: Optional[str]
    work_experience_years: Optional[float]
    experience_notes: List[str]
    age_years: Optional[int]
    publications_count: int
    updated_at: Optional[str]


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _profile_to_record(row: StudentProfile) -> StudentProfileRecord:
    return StudentProfileRecord(
        session_id=row.session_id,
        nationality=row.nationality,
        country_of_residence=row.country_of_residence,
        current_degree=row.current_degree,
        expected_graduation_year=row.expected_graduation_year,
        target_degree=row.target_degree,
        major=row.major,
        gpa_raw=row.gpa_raw,
        gpa_scale=row.gpa_scale,
        gpa_normalized_4=row.gpa_normalized_4,
        languages=list(row.languages_json or []),
        target_countries=list(row.target_countries_json or []),
        target_fields=list(row.target_fields_json or []),
        funding_need=row.funding_need,
        work_experience_years=row.work_experience_years,
        experience_notes=list(row.experience_notes or []),
        age_years=row.age_years,
        publications_count=int(row.publications_count or 0),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


class StudentRepository:
    """Stateless SQLAlchemy repository for student identity and profile records."""

    @staticmethod
    def get_active_consent(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
        row = (
            db.query(StudentConsent)
            .filter(
                StudentConsent.session_id == session_id,
                StudentConsent.revoked_at.is_(None),
            )
            .order_by(StudentConsent.id.desc())
            .first()
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "consent_version": row.consent_version,
            "scopes": dict(row.scopes_json or {}),
            "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        }

    @staticmethod
    def record_consent(
        db: Session,
        session_id: str,
        consent_version: str,
        scopes: Dict[str, bool],
    ) -> Dict[str, Any]:
        now = _utc_now_naive()
        entry = StudentConsent(
            session_id=session_id,
            consent_version=consent_version,
            scopes_json=dict(scopes),
            accepted_at=now,
        )
        db.add(entry)
        db.flush()
        return {
            "id": entry.id,
            "consent_version": entry.consent_version,
            "scopes": dict(entry.scopes_json or {}),
            "accepted_at": entry.accepted_at.isoformat(),
        }

    @staticmethod
    def get_profile(db: Session, session_id: str) -> Optional[StudentProfileRecord]:
        row = db.query(StudentProfile).filter(StudentProfile.session_id == session_id).first()
        if row is None:
            return None
        return _profile_to_record(row)

    @staticmethod
    def upsert_profile(
        db: Session,
        session_id: str,
        payload: Dict[str, Any],
    ) -> StudentProfileRecord:
        now = _utc_now_naive()
        row = db.query(StudentProfile).filter(StudentProfile.session_id == session_id).first()
        if row is None:
            row = StudentProfile(session_id=session_id, updated_at=now)

        row.nationality = payload["nationality"]
        row.country_of_residence = payload.get("country_of_residence")
        row.current_degree = payload.get("current_degree")
        row.expected_graduation_year = payload.get("expected_graduation_year")
        row.target_degree = payload.get("target_degree")
        row.major = payload.get("major")
        row.gpa_raw = payload.get("gpa_raw")
        row.gpa_scale = payload.get("gpa_scale")
        row.gpa_normalized_4 = payload.get("gpa_normalized_4")
        row.languages_json = list(payload.get("languages") or [])
        row.target_countries_json = list(payload.get("target_countries") or [])
        row.target_fields_json = list(payload.get("target_fields") or [])
        row.funding_need = payload.get("funding_need")
        row.work_experience_years = payload.get("work_experience_years")
        row.experience_notes = list(payload.get("experience_notes") or [])
        row.age_years = payload.get("age_years")
        row.publications_count = int(payload.get("publications_count") or 0)
        row.updated_at = now

        db.add(row)
        db.flush()
        return _profile_to_record(row)

    @staticmethod
    def list_consents(db: Session, session_id: str) -> List[Dict[str, Any]]:
        rows = (
            db.query(StudentConsent)
            .filter(StudentConsent.session_id == session_id)
            .order_by(StudentConsent.id.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "consent_version": r.consent_version,
                "scopes": dict(r.scopes_json or {}),
                "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            }
            for r in rows
        ]

    @staticmethod
    def count_optional_related_records(db: Session, session_id: str) -> Dict[str, int]:
        bind = db.get_bind()
        existing_tables = set(inspect(bind).get_table_names())
        counts: Dict[str, int] = {}
        for table in _OPTIONAL_SESSION_TABLES:
            if table in existing_tables:
                cnt = db.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE session_id = :sid"),
                    {"sid": session_id},
                ).scalar_one()
                counts[table] = int(cnt or 0)
            else:
                counts[table] = 0
        return counts

    @staticmethod
    def delete_all_session_data(db: Session, session_id: str) -> Dict[str, int]:
        """Atomically delete profile, consents, conversations/messages, optional child tables, and session."""
        removed: Dict[str, int] = {}
        bind = db.get_bind()
        existing_tables = set(inspect(bind).get_table_names())

        if "messages" in existing_tables and "conversations" in existing_tables:
            msg_res = db.execute(
                text(
                    "DELETE FROM messages WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE session_id = :sid)"
                ),
                {"sid": session_id},
            )
            removed["messages"] = int(msg_res.rowcount or 0)

        if "plan_items" in existing_tables and "application_plans" in existing_tables:
            pi_res = db.execute(
                text(
                    "DELETE FROM plan_items WHERE plan_id IN "
                    "(SELECT id FROM application_plans WHERE session_id = :sid)"
                ),
                {"sid": session_id},
            )
            removed["plan_items"] = int(pi_res.rowcount or 0)

        for table in _OPTIONAL_SESSION_TABLES:
            if table in existing_tables:
                res = db.execute(
                    text(f"DELETE FROM {table} WHERE session_id = :sid"),
                    {"sid": session_id},
                )
                removed[table] = int(res.rowcount or 0)
            else:
                removed[table] = 0

        removed["student_profiles"] = int(
            db.query(StudentProfile).filter(StudentProfile.session_id == session_id).delete()
        )
        removed["student_consents"] = int(
            db.query(StudentConsent).filter(StudentConsent.session_id == session_id).delete()
        )
        removed["student_sessions"] = int(
            db.query(StudentSession).filter(StudentSession.id == session_id).delete()
        )
        db.flush()
        return removed
