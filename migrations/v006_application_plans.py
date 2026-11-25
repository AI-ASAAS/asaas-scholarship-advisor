"""Migration 006: Personalized application_plans and plan_items tables (D11, Phase 6)."""

from sqlalchemy import Connection, inspect, text

VERSION = 6
DESCRIPTION = "Create application_plans and plan_items tables with session cascade"


def up(conn: Connection) -> None:
    inspector = inspect(conn)
    dialect = conn.dialect.name
    id_col = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    json_col = "JSONB" if dialect == "postgresql" else "JSON"
    dt_col = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    bool_false = "FALSE" if dialect == "postgresql" else "0"

    if not inspector.has_table("application_plans"):
        conn.execute(
            text(
                f"""
                CREATE TABLE application_plans (
                    id {id_col},
                    session_id VARCHAR(36) NOT NULL UNIQUE REFERENCES student_sessions(id) ON DELETE CASCADE,
                    created_at {dt_col} NOT NULL,
                    updated_at {dt_col} NOT NULL
                )
                """
            )
        )

    if not inspector.has_table("plan_items"):
        conn.execute(
            text(
                f"""
                CREATE TABLE plan_items (
                    id {id_col},
                    plan_id INTEGER NOT NULL REFERENCES application_plans(id) ON DELETE CASCADE,
                    grant_id INTEGER NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
                    priority_rank INTEGER NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'planned',
                    deadline_snapshot DATE,
                    checklist_json {json_col} NOT NULL DEFAULT '[]',
                    notes TEXT,
                    allow_ineligible BOOLEAN NOT NULL DEFAULT {bool_false},
                    created_at {dt_col} NOT NULL,
                    updated_at {dt_col} NOT NULL,
                    CONSTRAINT uq_plan_items_plan_grant UNIQUE (plan_id, grant_id)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_plan_items_plan_id ON plan_items (plan_id)"))
