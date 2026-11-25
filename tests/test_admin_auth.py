"""Admin authentication, cookie session, fail-closed, and rate-limit tests (D4)."""

from __future__ import annotations

from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.config import settings
from core.db import get_db
from core.repository import save_draft

ADMIN_KEY = "test-admin-key-123456"


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_admin_routes_fail_closed_when_key_unset(client: TestClient) -> None:
    """When ADMIN_API_KEY is unset, every protected endpoint denies access."""
    protected = [
        ("GET", "/api/system/status"),
        ("GET", "/api/agents/monitor/logs"),
        ("POST", "/api/agents/monitor/run"),
        ("GET", "/api/grants"),
        ("POST", "/api/grants/1/publish"),
        ("POST", "/api/agents/ingest"),
        ("POST", "/api/agents/ingest/preview"),
        ("POST", "/api/agents/search"),
    ]
    for method, path in protected:
        response = client.request(method, path)
        assert response.status_code == 401, (method, path)
        body = response.json()
        assert "message" in body and "code" in body


def test_admin_routes_reject_missing_or_wrong_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)

    assert client.get("/api/grants").status_code == 401
    assert client.get("/api/grants", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.post("/api/grants/1/publish").status_code == 401
    assert client.post("/api/agents/ingest", json={"official_url": "https://www.daad.de/x"}).status_code == 401
    assert client.post("/api/agents/search", json={"major": "CS", "degree_level": "Master"}).status_code == 401


def test_admin_cookie_login_session_and_logout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)

    # Unauthenticated session check
    s0 = client.get("/api/admin/session")
    assert s0.status_code == 200
    assert s0.json() == {"authenticated": False}

    # Wrong password rejected
    bad = client.post("/api/admin/login", json={"secret": "wrong-secret"})
    assert bad.status_code == 401
    assert bad.json()["code"] == "INVALID_CREDENTIALS"

    # Valid login sets HttpOnly, SameSite=lax cookie
    ok = client.post("/api/admin/login", json={"secret": ADMIN_KEY})
    assert ok.status_code == 200
    assert ok.json() == {"authenticated": True}
    set_cookie = ok.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()

    # Cookie authorizes protected endpoints
    assert client.get("/api/admin/session").json() == {"authenticated": True}
    listing = client.get("/api/grants")
    assert listing.status_code == 200
    assert "grants" in listing.json()
    assert client.get("/api/system/status").status_code == 200

    # Logout revokes session and clears cookie
    out = client.post("/api/admin/logout")
    assert out.status_code == 200
    assert out.json() == {"authenticated": False}
    assert client.get("/api/grants").status_code == 401


def test_admin_login_rate_limit_triggers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", 3)
    monkeypatch.setattr(settings, "LOGIN_RATE_WINDOW_SECONDS", 60)

    for _ in range(3):
        r = client.post("/api/admin/login", json={"secret": "wrong"})
        assert r.status_code == 401

    blocked = client.post("/api/admin/login", json={"secret": ADMIN_KEY})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    assert "Retry-After" in blocked.headers


def test_public_endpoints_never_leak_draft_or_expired_grants(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)

    with get_db() as db:
        draft = save_draft(
            db,
            {
                "title": "Hidden Draft Scholarship",
                "official_url": "https://example.org/hidden-draft",
                "deadline": date.today() + timedelta(days=20),
            },
        )
        draft_id = draft.id

    top10 = client.get("/api/grants/top10")
    assert top10.status_code == 200
    assert all(item["id"] != draft_id for item in top10.json())

    detail = client.get(f"/api/grants/{draft_id}")
    assert detail.status_code == 404

    list_attempt = client.get("/api/grants?status=draft")
    assert list_attempt.status_code == 401
