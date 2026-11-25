"""URL Validator module for verifying official scholarship links.

Enforces:
1. Shared SSRF / outbound URL guard (scheme, port, private/loopback/metadata IP, redirects).
2. Official / trusted domain verification against allowlist and aggregator blocklist.
3. HTTP 200 Alive check within bounded timeout and size cap.
4. Content match: verifies the grant name or relevant keywords appear in title or body.
"""

import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import httpx
from core.config import settings
from utils.url_guard import ResolveFn, UnsafeURLError, safe_request

# Common low-quality/ad scholarship aggregators that must be rejected
DISALLOWED_AGGREGATOR_KEYWORDS = [
    "scholarshipportal",
    "scholarship-positions",
    "opportunitiescorners",
    "wemakescholars",
    "heysuccess",
    "scholarshiproar",
    "opportunitiescircle",
    "youthop",
    "afterschoolafrica",
    "armacad",
]


def is_trusted_domain(url: str, trusted_domains: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Check if the URL's domain belongs to trusted official domains (no substring bypass)."""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except Exception:
        return False, "Malformed URL"

    if not hostname:
        return False, "Missing hostname in URL"

    # Check for known aggregators (label/host containment)
    for bad in DISALLOWED_AGGREGATOR_KEYWORDS:
        if bad in hostname:
            return False, f"Domain '{hostname}' is a known aggregator, not an official scholarship provider."

    allowed = trusted_domains or settings.trusted_domains

    # Check exact match or dot-bounded suffix match (never arbitrary substring match)
    for item in allowed:
        item = item.strip().lower().lstrip(".")
        if not item:
            continue
        if "." not in item:
            # Bare TLD such as "gov", "edu", "org": require ".<tld>" suffix
            if hostname.endswith("." + item):
                return True, f"Domain '{hostname}' matched trusted pattern '{item}'."
        else:
            if hostname == item or hostname.endswith("." + item):
                return True, f"Domain '{hostname}' matched trusted pattern '{item}'."

    # Allow official multi-label academic/government domains (e.g., ox.ac.uk, ku.edu.tr, gov.uk, europa.eu)
    if (
        hostname == "europa.eu"
        or hostname.endswith(".europa.eu")
        or re.fullmatch(r"[a-z0-9.-]+\.(?:gov|edu|ac)\.[a-z]{2}", hostname) is not None
    ):
        return True, f"Domain '{hostname}' matched official academic/government domain pattern."

    return False, f"Domain '{hostname}' is not in the trusted official domains allowlist."


def validate_official_url(
    url: str,
    grant_name: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
    resolve_fn: Optional[ResolveFn] = None,
) -> Tuple[bool, List[str]]:
    """Validate that a URL is safe, alive, official, and relevant to the grant."""
    reasons: List[str] = []

    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return False, ["URL must begin with http:// or https://"]

    def _check_hop(hop_url: str) -> None:
        domain_ok, domain_msg = is_trusted_domain(hop_url)
        if not domain_ok:
            raise UnsafeURLError(domain_msg)

    try:
        result = safe_request(
            "GET",
            url,
            client=client,
            resolve_fn=resolve_fn,
            timeout=timeout,
            hop_validator=_check_hop,
        )
    except UnsafeURLError as exc:
        reasons.append(str(exc))
        return False, reasons
    except (httpx.TimeoutException, httpx.ConnectTimeout):
        reasons.append(f"Connection timed out after {timeout} seconds.")
        return False, reasons
    except httpx.RequestError as exc:
        reasons.append(f"Network request error: {type(exc).__name__}")
        return False, reasons

    if result.status_code != 200:
        reasons.append(f"HTTP request failed with status code {result.status_code}")
        return False, reasons

    # Content match verification (if grant_name is specified)
    if grant_name and grant_name.strip():
        soup = BeautifulSoup(result.text, "html.parser")
        title_text = (soup.title.string or "") if soup.title else ""
        body_text = soup.get_text(separator=" ", strip=True)
        combined_page_text = f"{title_text} {body_text}".lower()

        raw_tokens = re.findall(r"[a-z0-9\u0600-\u06ff]+", grant_name.lower())
        significant_tokens = [
            t
            for t in raw_tokens
            if len(t) > 3 and t not in {"scholarship", "scholarships", "program", "programme"}
        ]

        if significant_tokens:
            matches = [t for t in significant_tokens if t in combined_page_text]
            if not matches:
                reasons.append(
                    f"Page content did not contain any core identifier keywords for '{grant_name}'. "
                    f"Expected at least one of: {significant_tokens}"
                )
                return False, reasons

    reasons.append("URL is alive (HTTP 200), verified official domain, and content matches.")
    return True, reasons
