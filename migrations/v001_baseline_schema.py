"""Migration 001: Phase 1 baseline schema (grants, update_logs).

Idempotent on existing databases created by Phase 1 `create_all`, and creates
exact baseline tables and indexes on fresh databases.
"""

from sqlalchemy import Connection, inspect, text

VERSION = 1
DESCRIPTION = "Baseline schema matching Phase 1 grants and update_logs tables"


def up(conn: Connection) -> None:
    inspector = inspect(conn)
    dialect = conn.dialect.name
    id_col = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    if not inspector.has_table("grants"):
        conn.execute(
            text(
                f"""
                CREATE TABLE grants (
                    id {id_col},
                    title VARCHAR(500) NOT NULL,
                    official_url VARCHAR(1000) NOT NULL,
                    description TEXT,
                    eligibility JSON,
                    criteria JSON,
                    fields_of_study JSON,
                    funding TEXT,
                    required_documents JSON,
                    deadline DATE,
                    how_to_apply TEXT,
                    accepts_yemeni VARCHAR(7) NOT NULL,
                    evidence JSON NOT NULL,
                    field_verification JSON NOT NULL,
                    status VARCHAR(9) NOT NULL,
                    content_hash VARCHAR(64),
                    last_checked_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_grants_official_url ON grants (official_url)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_grants_deadline ON grants (deadline)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_grants_status ON grants (status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_grants_status_deadline ON grants (status, deadline)"))

    if not inspector.has_table("update_logs"):
        conn.execute(
            text(
                f"""
                CREATE TABLE update_logs (
                    id {id_col},
                    grant_id INTEGER NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
                    field_name VARCHAR(100) NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    detected_at DATETIME NOT NULL,
                    notified BOOLEAN NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_update_logs_grant_id ON update_logs (grant_id)"))
