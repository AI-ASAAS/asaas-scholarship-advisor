"""Unit tests for URL Validator.

Verifies:
- Rejection of unknown or spam aggregator domains.
- Acceptance of trusted government / academic domains.
- HTTP status handling (200 OK vs 404 / 500 error).
- Grant name content matching.
"""

import httpx
import pytest
from utils.url_validator import is_trusted_domain, validate_official_url


def test_is_trusted_domain_accepts_official_domains():
    """Ensure trusted domains (e.g. .gov, .edu, specific whitelist) pass."""
    assert is_trusted_domain("https://www.turkiyeburslari.gov.tr/en")[0] is True
    assert is_trusted_domain("https://www.chevening.org/scholarships/")[0] is True
    assert is_trusted_domain("https://www.daad.de/scholarships")[0] is True
    assert is_trusted_domain("https://foreign.fulbrightonline.org/")[0] is True


def test_is_trusted_domain_rejects_aggregators_and_unknown():
    """Ensure spam aggregators and unknown domains are rejected."""
    # Aggregators
    assert is_trusted_domain("https://scholarship-positions.com/turkey-grant/")[0] is False
    assert is_trusted_domain("https://opportunitiescorners.com/chevening/")[0] is False
    # Unknown commercial site
    assert is_trusted_domain("https://random-commercial-site.xyz/scholarship")[0] is False


def test_validate_official_url_with_mock_client():
    """Test full validation pipeline using httpx MockTransport."""
    # Mock handler that simulates 200 OK with HTML content
    def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        if "404" in url_str:
            return httpx.Response(404, text="Not Found")
        if "turkiyeburslari" in url_str:
            html = """
            <html>
                <head><title>Türkiye Bursları Official Portal</title></head>
                <body>
                    <h1>Welcome to Türkiye Bursları</h1>
                    <p>Applications for international students are open.</p>
                </body>
            </html>
            """
            return httpx.Response(200, text=html)
        return httpx.Response(500, text="Server Error")

    transport = httpx.MockTransport(mock_handler)
    mock_client = httpx.Client(transport=transport)

    # 1. Valid URL + matching grant name
    valid, reasons = validate_official_url(
        url="https://www.turkiyeburslari.gov.tr/applications",
        grant_name="Türkiye Bursları",
        client=mock_client,
    )
    assert valid is True
    assert any("verified official domain" in r for r in reasons)

    # 2. Valid URL + mismatching grant name
    mismatch_valid, mismatch_reasons = validate_official_url(
        url="https://www.turkiyeburslari.gov.tr/applications",
        grant_name="Fulbright American Fellowship",
        client=mock_client,
    )
    assert mismatch_valid is False
    assert any("did not contain any core identifier keywords" in r for r in mismatch_reasons)

    # 3. HTTP 404 URL
    not_found_valid, not_found_reasons = validate_official_url(
        url="https://www.turkiyeburslari.gov.tr/404-page",
        grant_name="Türkiye Bursları",
        client=mock_client,
    )
    assert not_found_valid is False
    assert any("status code 404" in r for r in not_found_reasons)
