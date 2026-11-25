"""FastAPI boundary tests verifying ASAAS response, auth, and error contracts."""

from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.config import settings
from core.db import get_db
from core.models import GrantStatus
from core.repository import save_draft

ADMIN_KEY = "test-admin-secret-key-98765"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setattr(settings, "ADMIN_API_KEY", ADMIN_KEY)
    with TestClient(app) as test_client:
        yield test_client


def test_api_system_status_and_top10(client: TestClient):
    """Verify public top10 works without auth and system status works with admin session."""
    top10_res = client.get("/api/grants/top10")
    assert top10_res.status_code == 200
    assert isinstance(top10_res.json(), list)
    assert len(top10_res.json()) == 10

    unauth_status = client.get("/api/system/status")
    assert unauth_status.status_code == 401
    assert "message" in unauth_status.json()
    assert "code" in unauth_status.json()

    login_res = client.post("/api/admin/login", json={"secret": ADMIN_KEY})
    assert login_res.status_code == 200
    assert login_res.json()["authenticated"] is True

    status_res = client.get("/api/system/status")
    assert status_res.status_code == 200
    body = status_res.json()
    assert "llm_configured" in body
    assert "counts" in body
    assert body["dev_keys_enabled"] is False


def test_api_error_contract_returns_message_and_code(client: TestClient):
    """Verify 404, 422, and draft protection return standardized {"message", "code"} JSON."""
    not_found = client.get("/api/grants/999999")
    assert not_found.status_code == 404
    assert "message" in not_found.json()
    assert not_found.json()["code"] == "GRANT_NOT_FOUND"

    # Draft grant must NOT leak on public GET /api/grants/{id}
    with get_db() as db:
        draft = save_draft(
            db,
            {
                "title": "Secret Draft Grant",
                "official_url": "https://example.org/secret-draft",
                "deadline": date.today() + timedelta(days=30),
            },
        )
        draft_id = draft.id

    public_draft = client.get(f"/api/grants/{draft_id}")
    assert public_draft.status_code == 404
    assert public_draft.json()["code"] == "GRANT_NOT_FOUND"

    # Authenticated admin CAN view the draft and triggers 422 on invalid ingest payload
    admin_draft = client.get(f"/api/grants/{draft_id}", headers={"X-Admin-Key": ADMIN_KEY})
    assert admin_draft.status_code == 200
    assert admin_draft.json()["status"] == GrantStatus.DRAFT.value

    invalid_payload = client.post(
        "/api/agents/ingest",
        json={"official_url": "bad"},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert invalid_payload.status_code == 422
    assert "message" in invalid_payload.json()
    assert invalid_payload.json()["code"] == "VALIDATION_ERROR"


def test_api_keys_disabled_by_default_and_masked_when_dev_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Verify POST /api/system/keys is 404 by default and masks to last 4 chars only in dev mode."""
    import api.main as api_main

    # Disabled by default
    disabled_res = client.post(
        "/api/system/keys",
        json={"llm_api_key": "AIzaSyTestSecretKey9876"},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert disabled_res.status_code == 404

    temp_env = tmp_path / ".env"
    monkeypatch.setattr(api_main, "ENV_PATH", temp_env)
    monkeypatch.setattr(settings, "ENABLE_DEV_KEYS_ENDPOINT", True)
    monkeypatch.setattr(settings, "ALLOW_RUNTIME_ENV_WRITE", False)
    orig_llm = settings.LLM_API_KEY
    orig_tavily = settings.TAVILY_API_KEY
    orig_model = settings.LLM_MODEL

    try:
        res = client.post(
            "/api/system/keys",
            json={
                "llm_api_key": "AIzaSyTestSecretKey9876",
                "llm_model": "gemini-2.0-flash",
                "tavily_api_key": "tvly-TestSearchKey5432",
            },
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["llm_configured"] is True
        assert body["search_configured"] is True
        assert body["search_provider"] == "Tavily"
        # At most last 4 characters exposed (no prefix!)
        assert body["llm_key_hint"] == "••••9876"
        assert body["tavily_key_hint"] == "••••5432"
        assert "AIzaSyTestSecretKey9876" not in res.text
        assert "tvly-TestSearchKey5432" not in res.text
        assert not temp_env.exists()

        # When runtime env write IS allowed in local dev, keys persist to ENV_PATH
        monkeypatch.setattr(settings, "ALLOW_RUNTIME_ENV_WRITE", True)
        res_persist = client.post(
            "/api/system/keys",
            json={"tavily_api_key": "tvly-PersistCheck9988"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert res_persist.status_code == 200
        assert res_persist.json()["tavily_key_hint"] == "••••9988"
        assert temp_env.exists()
        assert "TAVILY_API_KEY=tvly-PersistCheck9988" in temp_env.read_text(encoding="utf-8")
    finally:
        settings.LLM_API_KEY = orig_llm
        settings.TAVILY_API_KEY = orig_tavily
        settings.LLM_MODEL = orig_model


def test_admin_manual_grant_crud_auto_expiry_and_models(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify admin manual grant CRUD, auto-expiry of past deadlines, and provider/model updates."""
    from datetime import date, timedelta
    import core.db as core_db

    # Unauthenticated rejections (violating cases)
    assert client.post("/api/grants", json={"title": "Test", "official_url": "https://example.edu/g"}).status_code == 401
    assert client.patch("/api/grants/1", json={"title": "Test 2"}).status_code == 401
    assert client.delete("/api/grants/1").status_code == 401
    assert client.post("/api/system/models", json={"llm_provider": "gemini"}).status_code == 401
    assert client.post("/api/system/test-keys").status_code == 401

    headers = {"X-Admin-Key": ADMIN_KEY}
    future_dl = (date.today() + timedelta(days=30)).isoformat()
    past_dl = (date.today() - timedelta(days=2)).isoformat()

    # Create manual grant published immediately
    created = client.post(
        "/api/grants",
        json={
            "title": "Manual Excellence Fellowship",
            "official_url": "https://example.edu/manual-fellowship",
            "host_country": "DE",
            "deadline": future_dl,
            "accepts_yemeni": "yes",
            "funding_type": "full",
            "allowed_degrees": ["master"],
            "min_gpa_value": 3.2,
            "min_gpa_scale": "4.0",
            "publish_immediately": True,
        },
        headers=headers,
    )
    assert created.status_code == 201
    g = created.json()
    gid = g["id"]
    assert g["status"] == "published"
    assert g["field_verification"]["title"] == "admin_manual"

    # Public top10 includes it
    top10 = client.get("/api/grants/top10").json()
    assert any(item["id"] == gid for item in top10)

    # Duplicate URL -> 409
    dup = client.post(
        "/api/grants",
        json={"title": "Dup", "official_url": "https://example.edu/manual-fellowship"},
        headers=headers,
    )
    assert dup.status_code == 409

    # Edit grant fields
    edited = client.patch(
        f"/api/grants/{gid}",
        json={"title": "Manual Excellence Updated", "featured_rank": 1},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "Manual Excellence Updated"
    assert edited.json()["featured_rank"] == 1

    # Simulate past deadline in DB -> public top10 drops it automatically and moves it to expired in admin
    with core_db.get_db() as db:
        from core.repository import get_grant_by_id

        row = get_grant_by_id(db, gid)
        assert row is not None
        row.deadline = date.fromisoformat(past_dl)
        db.add(row)

    top10_after = client.get("/api/grants/top10").json()
    assert all(item["id"] != gid for item in top10_after)
    expired_list = client.get("/api/grants?status=expired", headers=headers).json()
    assert any(item["id"] == gid and item["status"] == "expired" for item in expired_list["grants"])

    # Admin deletes the expired grant permanently
    deleted = client.delete(f"/api/grants/{gid}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/grants/{gid}", headers=headers).status_code == 404

    # Provider + Model selection and /api/system/models
    monkeypatch.setattr(settings, "ENABLE_DEV_KEYS_ENDPOINT", True)
    orig_provider = settings.LLM_PROVIDER
    orig_model = settings.LLM_MODEL
    orig_models_raw = settings.LLM_MODELS_RAW
    try:
        m_res = client.post(
            "/api/system/models",
            json={"llm_provider": "openai"},
            headers=headers,
        )
        assert m_res.status_code == 200
        assert "gpt-4o-mini" in m_res.json()["models"]

        k_res = client.post(
            "/api/system/keys",
            json={"llm_provider": "openai", "llm_model": "gpt-4o-mini"},
            headers=headers,
        )
        assert k_res.status_code == 200
        assert k_res.json()["llm_provider"] == "openai"
        assert k_res.json()["llm_model"] == "gpt-4o-mini"
        assert k_res.json()["llm_models"] == ["gpt-4o-mini"]

        t_res = client.post("/api/system/test-keys", headers=headers)
        assert t_res.status_code == 200
        assert t_res.json()["llm_provider"] == "openai"
        assert t_res.json()["llm_model"] == "gpt-4o-mini"
    finally:
        settings.LLM_PROVIDER = orig_provider
        settings.LLM_MODEL = orig_model
        settings.LLM_MODELS_RAW = orig_models_raw


def test_ingest_preview_does_not_persist_and_reports_existing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify POST /api/agents/ingest/preview returns extracted data without mutating DB."""
    import api.main as api_main

    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-gemini-key")

    future_dl = (date.today() + timedelta(days=45)).isoformat()
    sample_url = "https://www.ox.ac.uk/admissions/graduate/fees-and-funding/clarendon"

    def fake_extract(url: str):
        return {
            "title": "Clarendon Fund Preview Scholarship",
            "official_url": url,
            "description": "Fully funded UK master's scholarship.",
            "provider_name": "UK FCDO",
            "host_country": "United Kingdom",
            "deadline": date.fromisoformat(future_dl),
            "funding": "Full tuition, monthly stipend, flights",
            "funding_type": "full",
            "accepts_yemeni": "yes",
            "allowed_degrees": ["master"],
            "fields_of_study": ["Public Policy", "Computer Science"],
            "eligibility": ["Citizen of a Chevening-eligible country including Yemen"],
            "criteria": ["Leadership potential"],
            "required_documents": ["Passport", "Reference letters"],
            "how_to_apply": "Apply via the online Chevening portal.",
            "min_gpa_value": None,
            "min_gpa_scale": None,
            "min_gpa_normalized_4": None,
            "evidence": {"deadline": f"Applications close {future_dl}"},
            "field_verification": {"deadline": "verified", "title": "verified"},
        }

    monkeypatch.setattr(api_main, "extract_grant_preview", fake_extract)

    unauth = client.post("/api/agents/ingest/preview", json={"official_url": sample_url})
    assert unauth.status_code == 401

    headers = {"X-Admin-Key": ADMIN_KEY}
    before_count = len(client.get("/api/grants", headers=headers).json()["grants"])

    preview_res = client.post(
        "/api/agents/ingest/preview",
        json={"official_url": sample_url},
        headers=headers,
    )
    assert preview_res.status_code == 200
    body = preview_res.json()
    assert body["title"] == "Clarendon Fund Preview Scholarship"
    assert body["deadline"] == future_dl
    assert body["accepts_yemeni"] == "yes"
    assert body["already_exists_id"] is None
    assert body["evidence"]["deadline"] == f"Applications close {future_dl}"

    # Crucially, preview must NOT persist anything in the database
    after_count = len(client.get("/api/grants", headers=headers).json()["grants"])
    assert after_count == before_count

    # Once admin saves manually, preview reports already_exists_id so UI edits instead of duplicating
    saved_res = client.post(
        "/api/grants",
        json={
            "title": body["title"],
            "official_url": body["official_url"],
            "deadline": body["deadline"],
            "accepts_yemeni": body["accepts_yemeni"],
            "evidence": body["evidence"],
            "publish_immediately": False,
        },
        headers=headers,
    )
    assert saved_res.status_code == 201
    created_id = saved_res.json()["id"]

    preview_existing = client.post(
        "/api/agents/ingest/preview",
        json={"official_url": sample_url},
        headers=headers,
    )
    assert preview_existing.status_code == 200
    assert preview_existing.json()["already_exists_id"] == created_id
    assert preview_existing.json()["already_exists_status"] == "draft"
    assert len(client.get("/api/grants", headers=headers).json()["grants"]) == before_count + 1
