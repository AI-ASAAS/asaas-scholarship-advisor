"""Tests for the shared outbound URL / SSRF guard (utils/url_guard.py)."""

from __future__ import annotations

import ipaddress
import httpx
import pytest

from utils.url_guard import UnsafeURLError, safe_request, validate_outbound_url
from utils.url_validator import is_trusted_domain, validate_official_url


def _public_resolver(_host: str, _port: int):
    return [ipaddress.ip_address("93.184.216.34")]


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://localhost/admin",
        "http://127.0.0.1/status",
        "http://10.0.0.1/internal",
        "http://172.16.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://2130706433/",       # decimal 127.0.0.1
        "http://0177.0.0.1/",       # octal 127.0.0.1
        "http://0x7f000001/",       # hex 127.0.0.1
        "http://127.1/",            # shorthand 127.0.0.1
        "https://user:pass@www.daad.de/scholarships",
        "https://www.daad.de:8443/scholarships",
        "file:///etc/passwd",
        "ftp://www.daad.de/file",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_validate_outbound_url_rejects_ssrf_vectors(bad_url: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(bad_url, resolve_fn=_public_resolver)


def test_validate_outbound_url_rejects_dns_resolving_to_private_ip() -> None:
    def private_dns(_host: str, _port: int):
        return [ipaddress.ip_address("10.12.34.56")]

    with pytest.raises(UnsafeURLError):
        validate_outbound_url("https://www.daad.de/scholarships", resolve_fn=private_dns)


def test_is_trusted_domain_blocks_substring_spoofing() -> None:
    assert is_trusted_domain("https://evil-gov.com/phish")[0] is False
    assert is_trusted_domain("https://myorg.attacker.com/x")[0] is False
    assert is_trusted_domain("https://www.daad.de/en/scholarships")[0] is True
    assert is_trusted_domain("https://education.gov/grants")[0] is True


def test_safe_request_blocks_redirect_from_public_to_private_ip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "daad.de" in str(request.url):
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, text="SECRET_METADATA")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UnsafeURLError):
        safe_request(
            "GET",
            "https://www.daad.de/redirect-me",
            client=client,
            resolve_fn=_public_resolver,
        )


def test_safe_request_rejects_oversized_response_body() -> None:
    big_html = "<html><body>" + ("A" * 5000) + "</body></html>"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=big_html,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UnsafeURLError):
        safe_request(
            "GET",
            "https://www.daad.de/big",
            client=client,
            resolve_fn=_public_resolver,
            max_bytes=1024,
        )


def test_validate_official_url_allows_legitimate_official_url() -> None:
    html = (
        "<html><head><title>DAAD Master Scholarship</title></head>"
        "<body><p>Official DAAD scholarship portal.</p></body></html>"
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _req: httpx.Response(
                200, text=html, headers={"Content-Type": "text/html; charset=utf-8"}
            )
        )
    )
    ok, reasons = validate_official_url(
        "https://www.daad.de/en/scholarships",
        grant_name="DAAD",
        client=client,
        resolve_fn=_public_resolver,
    )
    assert ok is True
    assert any("verified official domain" in r for r in reasons)
