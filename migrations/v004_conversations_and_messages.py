"""Migration 004: Scoped advisor conversations and messages (D8, D12)."""

from sqlalchemy import Connection, inspect, text

VERSION = 4
DESCRIPTION = "Create conversations and messages tables for advisor chat retention"


def up(conn: Connection) -> None:
    inspector = inspect(conn)
    dialect = conn.dialect.name
    id_col = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    if not inspector.has_table("conversations"):
        conn.execute(
            text(
                """
                CREATE TABLE conversations (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL REFERENCES student_sessions(id) ON DELETE CASCADE,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_conversations_session_id ON conversations (session_id)")
        )

    if not inspector.has_table("messages"):
        conn.execute(
            text(
                f"""
                CREATE TABLE messages (
                    id {id_col},
                    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role VARCHAR(16) NOT NULL,
                    content TEXT NOT NULL,
                    attachments_json JSON NOT NULL,
                    prompt_version VARCHAR(64),
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_messages_created_at ON messages (created_at)")
        )
