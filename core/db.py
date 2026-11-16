"""Database connection and session management module.

Applies ASAAS SQLite standards (WAL mode, foreign keys, busy timeout)
while remaining fully portable to PostgreSQL.
"""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from core.config import settings
from core.models import Base

# Database engine configuration
DATABASE_URL = settings.DATABASE_URL
connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    future=True,
)

# Apply SQLite specific production optimizations if running on SQLite
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # Enable Foreign Key constraints
        cursor.execute("PRAGMA foreign_keys = ON;")
        # Enable Write-Ahead Logging for high concurrency
        cursor.execute("PRAGMA journal_mode = WAL;")
        # Set busy timeout to 5000ms to prevent database locked errors
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def init_db(target_engine=None) -> None:
    """Create all tables in the database if they do not exist."""
    bind = target_engine or engine
    Base.metadata.create_all(bind=bind)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager for transactional database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
