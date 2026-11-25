"""Phase 8 security hardening, ownership checks, health probe, and D12 retention tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from api.main import app
from core.db import get_db
from core.models import (
    ApplicationPlan,
    ChatMessage,
    Conversation,
    DocumentDraft,
    ExternalSearchCache,
    Grant,
    GrantStatus,
    Notification,
    StudentConsent,
    StudentProfile,
    StudentSession,
)
from modules.assistant.schemas import AssistantAskRequest
from modules.assistant.service import AssistantService
from modules.auth.schemas import StudentPrincipal
from modules.search.service import SearchRunBudget, cancel_active_run
from modules.students.retention import run_retention_cleanup


def _create_consented_student(client: TestClient, major: str = "Computer Science") -> None:
    assert client.post("/api/students/session", json={"consent_accepted": True}).status_code == 200
    assert (
        client.put(
            "/api/students/profile",
            json={
                "nationality": "YE",
                "target_degree": "master",
                "major": major,
                "gpa_raw": "3.6",
                "gpa_scale": "4.0",
                "languages": [{"language": "English", "test_name": "IELTS", "score": 6.5}],
            },
        ).status_code
        == 200
    )


def test_public_health_and_unauthenticated_external_search_blocked(monkeypatch):
    from core.config import settings

    with TestClient(app) as client:
        # 1. Public minimal /api/health works without auth and exposes zero config/secrets
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        # 2. Unauthenticated caller CANNOT trigger external search or cancel endpoint
        monkeypatch.setattr(settings, "TAVILY_API_KEY", "test-tavily-dummy")
        unauth_search = client.post(
            "/api/search/external",
            json={"nationality": "YE", "target_degree": "master", "major": "AI", "use_cache": False},
        )
        assert unauth_search.status_code == 401
        unauth_cancel = client.post("/api/search/external/run-123/cancel")
        assert unauth_cancel.status_code == 401

        # 3. Authenticated student CAN call search & cancel
        _create_consented_student(client)
        monkeypatch.setattr(
            "modules.search.router._service._search_fn",
            lambda _q, _n: [],
        )
        auth_search = client.post(
            "/api/search/external",
            json={"nationality": "YE", "target_degree": "master", "major": "AI", "use_cache": False},
        )
        assert auth_search.status_code == 200


def test_cross_student_cancel_and_sec_fetch_site_cross_site_blocked():
    from migrations.runner import run_migrations
    import core.db as core_db

    run_migrations(core_db.engine)

    # 1. Ownership check on active search run cancellation
    from modules.search.service import _ACTIVE_BUDGETS, _ACTIVE_LOCK

    budget = SearchRunBudget(
        max_queries=1,
        max_pages=2,
        max_steps=5,
        wall_clock_seconds=10.0,
        max_tokens=1000,
    )
    with _ACTIVE_LOCK:
        _ACTIVE_BUDGETS["run-owned-by-a"] = (budget, "student-a")
    try:
        # Student B cannot cancel Student A's run
        assert cancel_active_run("run-owned-by-a", session_id="student-b") is False
        assert budget.cancelled is False
        # Student A CAN cancel its own run
        assert cancel_active_run("run-owned-by-a", session_id="student-a") is True
        assert budget.cancelled is True
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_BUDGETS.pop("run-owned-by-a", None)

    # 2. Cross-site Sec-Fetch-Site header rejected on cookie-authenticated mutations
    with TestClient(app) as client:
        _create_consented_student(client)
        blocked = client.put(
            "/api/students/profile",
            headers={"Sec-Fetch-Site": "cross-site"},
            json={
                "nationality": "YE",
                "target_degree": "master",
                "major": "Physics",
            },
        )
        assert blocked.status_code in (401, 403)
        assert client.get("/api/students/profile").json()["major"] == "Computer Science"

        blocked_plan = client.post(
            "/api/plan/items",
            headers={"Sec-Fetch-Site": "cross-site"},
            json={"grant_id": 1},
        )
        assert blocked_plan.status_code == 401

        allowed = client.put(
            "/api/students/profile",
            headers={"Sec-Fetch-Site": "same-origin"},
            json={
                "nationality": "YE",
                "target_degree": "master",
                "major": "Physics",
            },
        )
        assert allowed.status_code == 200


def test_assistant_scrubs_accidental_pii_from_user_chat():
    class _SpyLLM:
        def __init__(self):
            self.seen_payloads = []

        async def chat(self, messages, **_kwargs):
            self.seen_payloads.append(messages)
            return {"content": "يمكنني مساعدتك في منح الماجستير حسب ملفك.", "tool_calls": []}

    spy = _SpyLLM()
    svc = AssistantService(spy)  # type: ignore[arg-type]
    principal = StudentPrincipal(session_id="pii-chat-sid", authenticated=True, has_consent=True)
    req = AssistantAskRequest(
        messages=[
            {
                "role": "user",
                "content": "أنا طالب يمني في الماجستير، بريدي ahmed.test@example.com وهاتفي +967771234567 ورقم هويتي 1234567890 ما أنسب المنح؟",
            }
        ]
    )
    res, _trace = asyncio.run(svc.ask_with_trace(principal, req, persist=False))
    assert "منح الماجستير" in res.reply
    sent_blob = str(spy.seen_payloads)
    assert "ahmed.test@example.com" not in sent_blob
    assert "+967771234567" not in sent_blob
    assert "1234567890" not in sent_blob


def test_d12_retention_cleanup_time_shifted():
    from migrations.runner import run_migrations
    import core.db as core_db

    run_migrations(core_db.engine)

    now = datetime(2026, 12, 1, 12, 0, 0)
    with get_db() as db:
        # Expired student session (past 90 days) + child records -> must all vanish
        expired_sid = "expired-session-1"
        db.add(
            StudentSession(
                id=expired_sid,
                token_hash="hash-exp",
                created_at=now - timedelta(days=120),
                last_seen_at=now - timedelta(days=95),
                expires_at=now - timedelta(days=5),
            )
        )
        db.add(
            StudentConsent(
                session_id=expired_sid,
                consent_version="privacy-v1",
                scopes_json={"profile_storage": True},
                accepted_at=now - timedelta(days=120),
            )
        )
        db.add(
            StudentProfile(
                session_id=expired_sid,
                nationality="YE",
                target_degree="master",
                major="IT",
                updated_at=now - timedelta(days=95),
            )
        )

        # Active student session -> kept, but stale (>30d) chat message & stale (>90d) draft & old read notif are purged
        active_sid = "active-session-2"
        db.add(
            StudentSession(
                id=active_sid,
                token_hash="hash-act",
                created_at=now - timedelta(days=100),
                last_seen_at=now - timedelta(days=1),
                expires_at=now + timedelta(days=89),
            )
        )
        conv_old = Conversation(
            id="conv-old-1",
            session_id=active_sid,
            created_at=now - timedelta(days=45),
            updated_at=now - timedelta(days=40),
        )
        conv_fresh = Conversation(
            id="conv-fresh-2",
            session_id=active_sid,
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(days=1),
        )
        db.add_all([conv_old, conv_fresh])
        db.flush()

        db.add(
            ChatMessage(
                conversation_id=conv_old.id,
                role="user",
                content="old msg",
                created_at=now - timedelta(days=40),
            )
        )
        db.add(
            ChatMessage(
                conversation_id=conv_fresh.id,
                role="user",
                content="fresh msg",
                created_at=now - timedelta(days=2),
            )
        )
        db.add(
            DocumentDraft(
                session_id=active_sid,
                doc_type="cv",
                language="ar",
                facts_ledger_json=[],
                draft_text="old draft",
                flagged_claims_json=[],
                created_at=now - timedelta(days=100),
                updated_at=now - timedelta(days=95),
            )
        )
        db.add(
            DocumentDraft(
                session_id=active_sid,
                doc_type="cv",
                language="ar",
                facts_ledger_json=[],
                draft_text="fresh draft",
                flagged_claims_json=[],
                created_at=now - timedelta(days=5),
                updated_at=now - timedelta(days=2),
            )
        )
        db.add(
            Notification(
                session_id=active_sid,
                kind="deadline_7d",
                title="Old read",
                body="old",
                is_read=True,
                dedupe_key="old-read-1",
                created_at=now - timedelta(days=95),
            )
        )
        db.add(
            Notification(
                session_id=active_sid,
                kind="deadline_3d",
                title="Fresh unread",
                body="fresh",
                is_read=False,
                dedupe_key="fresh-unread-1",
                created_at=now - timedelta(days=1),
            )
        )
        db.add(
            ExternalSearchCache(
                query_hash="expired-cache-hash",
                results_json={"results": []},
                created_at=now - timedelta(hours=48),
                expires_at=now - timedelta(hours=1),
            )
        )
        db.add(
            ExternalSearchCache(
                query_hash="fresh-cache-hash",
                results_json={"results": []},
                created_at=now - timedelta(hours=1),
                expires_at=now + timedelta(hours=23),
            )
        )
        db.commit()

        summary = run_retention_cleanup(db, now=now)
        db.commit()

        assert summary["expired_sessions"] == 1
        assert summary["expired_messages"] == 1
        assert summary["empty_conversations"] == 1
        assert summary["expired_drafts"] == 1
        assert summary["expired_read_notifications"] == 1
        assert summary["expired_search_cache"] == 1

        # Legitimate active records survive!
        assert db.query(StudentSession).filter(StudentSession.id == active_sid).first() is not None
        assert db.query(ChatMessage).count() == 1
        assert db.query(Conversation).count() == 1
        assert db.query(DocumentDraft).count() == 1
        assert db.query(Notification).count() == 1
        assert db.query(ExternalSearchCache).count() == 1
