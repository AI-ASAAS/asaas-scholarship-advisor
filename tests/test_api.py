"""FastAPI boundary tests verifying ASAAS response and error contracts."""

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_api_system_status_and_top10():
    """Verify system status and top 10 endpoints return valid typed JSON."""
    status_res = client.get("/api/system/status")
    assert status_res.status_code == 200
    body = status_res.json()
    assert "llm_configured" in body
    assert "counts" in body

    top10_res = client.get("/api/grants/top10")
    assert top10_res.status_code == 200
    assert isinstance(top10_res.json(), list)


def test_api_error_contract_returns_message_field():
    """Verify 404 and 422 errors return ASAAS standardized `{"message": "..."}` JSON."""
    not_found = client.get("/api/grants/999999")
    assert not_found.status_code == 404
    assert "message" in not_found.json()

    invalid_payload = client.post("/api/agents/ingest", json={"official_url": "bad"})
    assert invalid_payload.status_code == 422
    assert "message" in invalid_payload.json()


def test_api_telegram_dry_run_filters_and_deduplicates():
    """Verify Telegram watcher endpoint extracts official URLs and rejects spam links."""
    posts = [
        "Official: https://www.daad.de/en/new-test-scholarship and fake https://t.me/fake_channel and https://scholarship-positions.com/x"
    ]
    res = client.post("/api/agents/telegram/process", json={"posts": posts, "dry_run": True})
    assert res.status_code == 200
    data = res.json()
    assert data["trusted_urls_found"] == 1
    assert len(data["skipped_untrusted"]) == 2


def test_api_update_keys_activates_live_and_masks_secrets(monkeypatch, tmp_path):
    """Verify POST /api/system/keys applies keys immediately and returns only masked previews."""
    import api.main as api_main
    from core.config import settings

    temp_env = tmp_path / ".env"
    monkeypatch.setattr(api_main, "ENV_PATH", temp_env)
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
        )
        assert res.status_code == 200
        body = res.json()
        assert body["llm_configured"] is True
        assert body["search_configured"] is True
        assert body["search_provider"] == "Tavily"
        assert body["llm_key_hint"] == "AIza••••9876"
        assert body["tavily_key_hint"] == "tvly••••5432"
        # Full secret must NEVER be leaked in API response
        assert "AIzaSyTestSecretKey9876" not in res.text
        assert "tvly-TestSearchKey5432" not in res.text
    finally:
        settings.LLM_API_KEY = orig_llm
        settings.TAVILY_API_KEY = orig_tavily
        settings.LLM_MODEL = orig_model
