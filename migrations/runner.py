"""Ordered SQLAlchemy migration runner (D2).

Supports both SQLite and PostgreSQL without extra dependencies.
Usage:
    python -m migrations.runner
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Protocol
from sqlalchemy import Engine, text
from migrations import (
    v001_baseline_schema,
    v002_grant_structured_eligibility_and_curation,
    v003_student_sessions_profiles_consents,
    v004_conversations_and_messages,
    v005_document_drafts,
    v006_application_plans,
    v007_notifications_and_search_cache,
)

logger = logging.getLogger(__name__)


class MigrationModule(Protocol):
    VERSION: int
    DESCRIPTION: str

    def up(self, conn) -> None: ...


MIGRATIONS: List[MigrationModule] = [
    v001_baseline_schema,
    v002_grant_structured_eligibility_and_curation,
    v003_student_sessions_profiles_consents,
    v004_conversations_and_messages,
    v005_document_drafts,
    v006_application_plans,
    v007_notifications_and_search_cache,
]

_CREATE_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description VARCHAR(255) NOT NULL,
    applied_at VARCHAR(64) NOT NULL
)
"""


def run_migrations(target_engine: Engine) -> List[int]:
    """Apply all pending ordered migrations inside explicit transactions.

    Returns the list of migration versions applied during this invocation.
    """
    applied_now: List[int] = []

    with target_engine.begin() as conn:
        conn.execute(text(_CREATE_MIGRATIONS_TABLE_SQL))
        existing_rows = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version")).fetchall()
        applied_versions = {int(row[0]) for row in existing_rows}

    for mig in MIGRATIONS:
        if mig.VERSION in applied_versions:
            continue
        with target_engine.begin() as conn:
            mig.up(conn)
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, description, applied_at) "
                    "VALUES (:version, :description, :applied_at)"
                ),
                {
                    "version": mig.VERSION,
                    "description": mig.DESCRIPTION,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        applied_now.append(mig.VERSION)
        logger.info("Applied migration %03d: %s", mig.VERSION, mig.DESCRIPTION)

    return applied_now


def get_applied_migrations(target_engine: Engine) -> List[Dict[str, str]]:
    """Return applied schema migration rows ordered by version."""
    with target_engine.begin() as conn:
        conn.execute(text(_CREATE_MIGRATIONS_TABLE_SQL))
        rows = conn.execute(
            text("SELECT version, description, applied_at FROM schema_migrations ORDER BY version ASC")
        ).mappings().all()
        return [
            {
                "version": str(row["version"]),
                "description": str(row["description"]),
                "applied_at": str(row["applied_at"]),
            }
            for row in rows
        ]


if __name__ == "__main__":
    from core.db import engine

    newly_applied = run_migrations(engine)
    rows = get_applied_migrations(engine)
    print(f"Newly applied: {newly_applied}")
    for row in rows:
        print(f"  v{int(row['version']):03d} | {row['description']} | {row['applied_at']}")
