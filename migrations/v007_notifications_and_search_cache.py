"""Migration 007: Notifications inbox, external search cache, and monitor change review queue (D10, D11)."""

from sqlalchemy import Connection, inspect, text

VERSION = 7
DESCRIPTION = "Create notifications, external_search_cache, and grant_change_reviews tables"


def up(conn: Connection) -> None:
    inspector = inspect(conn)
    dialect = conn.dialect.name
    id_col = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    json_col = "JSONB" if dialect == "postgresql" else "JSON"
    dt_col = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    bool_false = "FALSE" if dialect == "postgresql" else "0"

    if not inspector.has_table("notifications"):
        conn.execute(
            text(
                f"""
                CREATE TABLE notifications (
                    id {id_col},
                    session_id VARCHAR(36) NOT NULL REFERENCES student_sessions(id) ON DELETE CASCADE,
                    grant_id INTEGER REFERENCES grants(id) ON DELETE SET NULL,
                    kind VARCHAR(48) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    body TEXT NOT NULL,
                    official_url VARCHAR(1000),
                    is_read BOOLEAN NOT NULL DEFAULT {bool_false},
                    dedupe_key VARCHAR(128) NOT NULL,
                    created_at {dt_col} NOT NULL,
                    CONSTRAINT uq_notifications_session_dedupe UNIQUE (session_id, dedupe_key)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_session_id ON notifications (session_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at)"))

    if not inspector.has_table("external_search_cache"):
        conn.execute(
            text(
                f"""
                CREATE TABLE external_search_cache (
                    query_hash VARCHAR(64) PRIMARY KEY,
                    results_json {json_col} NOT NULL,
                    created_at {dt_col} NOT NULL,
                    expires_at {dt_col} NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_external_search_cache_expires ON external_search_cache (expires_at)"))

    if not inspector.has_table("grant_change_reviews"):
        conn.execute(
            text(
                f"""
                CREATE TABLE grant_change_reviews (
                    id {id_col},
                    grant_id INTEGER NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
                    update_log_id INTEGER REFERENCES update_logs(id) ON DELETE SET NULL,
                    field_name VARCHAR(100) NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    summary_ar TEXT NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    reviewed_at {dt_col},
                    created_at {dt_col} NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_grant_change_reviews_status ON grant_change_reviews (status)"))
