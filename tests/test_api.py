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
