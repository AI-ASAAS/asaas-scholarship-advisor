"""Migration 003: Student sessions, consents, and profiles (D4, D12)."""

from sqlalchemy import Connection, inspect, text

VERSION = 3
DESCRIPTION = "Create student_sessions, student_consents, and student_profiles tables"


def up(conn: Connection) -> None:
    inspector = inspect(conn)
    dialect = conn.dialect.name
    id_col = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    if not inspector.has_table("student_sessions"):
        conn.execute(
            text(
                """
                CREATE TABLE student_sessions (
                    id VARCHAR(36) PRIMARY KEY,
                    token_hash VARCHAR(64) NOT NULL UNIQUE,
                    created_at DATETIME NOT NULL,
                    last_seen_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_student_sessions_token_hash ON student_sessions (token_hash)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_student_sessions_last_seen_at ON student_sessions (last_seen_at)")
        )

    if not inspector.has_table("student_consents"):
        conn.execute(
            text(
                f"""
                CREATE TABLE student_consents (
                    id {id_col},
                    session_id VARCHAR(36) NOT NULL REFERENCES student_sessions(id) ON DELETE CASCADE,
                    consent_version VARCHAR(32) NOT NULL,
                    scopes_json JSON NOT NULL,
                    accepted_at DATETIME NOT NULL,
                    revoked_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_student_consents_session_id ON student_consents (session_id)")
        )

    if not inspector.has_table("student_profiles"):
        conn.execute(
            text(
                """
                CREATE TABLE student_profiles (
                    session_id VARCHAR(36) PRIMARY KEY REFERENCES student_sessions(id) ON DELETE CASCADE,
                    nationality VARCHAR(8) NOT NULL DEFAULT 'YE',
                    country_of_residence VARCHAR(8),
                    current_degree VARCHAR(24),
                    expected_graduation_year INTEGER,
                    target_degree VARCHAR(24),
                    major VARCHAR(160),
                    gpa_raw VARCHAR(32),
                    gpa_scale VARCHAR(20),
                    gpa_normalized_4 FLOAT,
                    languages_json JSON NOT NULL,
                    target_countries_json JSON NOT NULL,
                    target_fields_json JSON NOT NULL,
                    funding_need VARCHAR(32),
                    work_experience_years FLOAT,
                    experience_notes JSON NOT NULL,
                    age_years INTEGER,
                    publications_count INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
