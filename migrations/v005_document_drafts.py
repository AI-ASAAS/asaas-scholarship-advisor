"""Migration 005: Saved student application document drafts (D9, D12)."""

from sqlalchemy import Connection, inspect, text

VERSION = 5
DESCRIPTION = "Create document_drafts table with student session cascade and retention index"


def up(conn: Connection) -> None:
    inspector = inspect(conn)
    dialect = conn.dialect.name
    id_col = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    json_col = "JSONB" if dialect == "postgresql" else "JSON"
    dt_col = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    if not inspector.has_table("document_drafts"):
        conn.execute(
            text(
                f"""
                CREATE TABLE document_drafts (
                    id {id_col},
                    session_id VARCHAR(36) NOT NULL REFERENCES student_sessions(id) ON DELETE CASCADE,
                    grant_id INTEGER REFERENCES grants(id) ON DELETE SET NULL,
                    doc_type VARCHAR(32) NOT NULL,
                    language VARCHAR(8) NOT NULL DEFAULT 'ar',
                    facts_ledger_json {json_col} NOT NULL DEFAULT '[]',
                    draft_text TEXT NOT NULL,
                    flagged_claims_json {json_col} NOT NULL DEFAULT '[]',
                    prompt_version VARCHAR(64),
                    created_at {dt_col} NOT NULL,
                    updated_at {dt_col} NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_document_drafts_session_id ON document_drafts (session_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_document_drafts_created_at ON document_drafts (created_at)")
        )
