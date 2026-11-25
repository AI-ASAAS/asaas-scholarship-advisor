"""Test-suite isolation helpers.

Isolates all root tests that touch ``core.db`` (``test_seed.py``,
``test_api.py``, ``test_admin_auth.py``, ``test_security_phase1.py``) to a
temporary SQLite database per test, so running pytest never reads or mutates
the developer's ``grants.db`` or ``.env`` state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base


_DB_TEST_FILES = {
    "test_seed.py",
    "test_api.py",
    "test_admin_auth.py",
    "test_security_phase1.py",
    "test_phase2_foundation.py",
    "test_phase3_students_matching.py",
    "test_phase4_assistant.py",
    "test_phase5_documents.py",
    "test_phase6_plans.py",
    "test_phase7_search_monitor.py",
    "test_phase8_hardening_retention.py",
}


@pytest.fixture(autouse=True)
def isolate_root_db_and_auth(request, tmp_path, monkeypatch):
    node_path = Path(str(getattr(request.node, "path", request.node.fspath)))
    if "agent_platform" in node_path.parts:
        yield
        return

    from api import main as api_main
    from modules.assistant import router as assistant_router
    from modules.auth.service import clear_auth_state_for_tests
    from modules.documents import router as documents_router
    from modules.matching import router as matching_router
    from modules.plans import router as plans_router
    from modules.search import router as search_router

    clear_auth_state_for_tests()
    api_main.ingest_rate_limiter.reset()
    api_main.search_rate_limiter.reset()
    matching_router.matches_rate_limiter.reset()
    matching_router.analysis_rate_limiter.reset()
    assistant_router.assistant_session_limiter.reset()
    assistant_router.assistant_ip_limiter.reset()
    documents_router.documents_rate_limiter.reset()
    plans_router.plans_rate_limiter.reset()
    search_router.student_external_search_limiter.reset()
    search_router.ip_external_search_limiter.reset()
    search_router.global_external_search_limiter.reset()

    if node_path.name not in _DB_TEST_FILES:
        yield
        return

    import core.db as core_db
    from core.config import settings

    # Ensure tests never depend on developer .env admin/dev flags
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL_ADMIN", raising=False)
    monkeypatch.setattr(settings, "ADMIN_API_KEY", None)
    monkeypatch.setattr(settings, "ALLOW_INSECURE_LOCAL_ADMIN", False)
    monkeypatch.setattr(settings, "ENABLE_DEV_KEYS_ENDPOINT", False)
    monkeypatch.setattr(settings, "ALLOW_RUNTIME_ENV_WRITE", False)

    db_file = tmp_path / "grants_test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    if node_path.name == "test_seed.py":
        Base.metadata.create_all(engine)

    session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr(core_db, "engine", engine)
    monkeypatch.setattr(core_db, "SessionLocal", session_local)

    yield
    engine.dispose()
