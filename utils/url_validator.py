"""URL Validator module for verifying official scholarship links.

Enforces:
1. HTTP 200 Alive check within 10 seconds.
2. Official / trusted domain verification against allowlist and aggregator blocklist.
3. Content match: verifies the grant name or relevant keywords appear in title or body.
"""

from typing import List, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import httpx
from core.config import settings

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
    """Check if the URL's domain belongs to trusted official domains."""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return False, "Malformed URL"

    if not hostname:
        return False, "Missing hostname in URL"

    # Check for known aggregators
    for bad in DISALLOWED_AGGREGATOR_KEYWORDS:
        if bad in hostname:
            return False, f"Domain '{hostname}' is a known aggregator, not an official scholarship provider."

    allowed = trusted_domains or settings.trusted_domains

    # Check if host matches or ends with any allowed domain/TLD
    for item in allowed:
        item = item.strip().lower()
        if not item:
            continue
        # Exact match or subdomain match (e.g. "turkiyeburslari.gov.tr" in host or host.endswith(".gov"))
        if hostname == item or hostname.endswith("." + item) or item in hostname:
            return True, f"Domain '{hostname}' matched trusted pattern '{item}'."

    return False, f"Domain '{hostname}' is not in the trusted official domains allowlist."


def validate_official_url(
    url: str,
    grant_name: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> Tuple[bool, List[str]]:
    """Validate that a URL is alive, official, and relevant to the grant.

    Returns:
        (is_valid: bool, reasons: List[str])
    """
    reasons: List[str] = []

    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return False, ["URL must begin with http:// or https://"]

    # 1. Domain verification
    domain_ok, domain_msg = is_trusted_domain(url)
    if not domain_ok:
        reasons.append(domain_msg)
        return False, reasons

    # 2. HTTP Alive check & Content retrieval
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 DiscoveryAgent/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    should_close_client = False
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=True, headers=headers)
        should_close_client = True

    try:
        response = client.get(url)
        if response.status_code != 200:
            reasons.append(f"HTTP request failed with status code {response.status_code}")
            return False, reasons

        # 3. Content match verification (if grant_name is specified)
        if grant_name and grant_name.strip():
            html_text = response.text
            soup = BeautifulSoup(html_text, "html.parser")
            title_text = (soup.title.string or "") if soup.title else ""
            body_text = soup.get_text(separator=" ", strip=True)

            combined_page_text = f"{title_text} {body_text}".lower()

            # Split grant name into meaningful tokens (ignore short words like "of", "the", "in")
            raw_tokens = grant_name.lower().split()
            significant_tokens = [t for t in raw_tokens if len(t) > 3 and t not in {"scholarship", "scholarships", "program", "programme"}]

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

    except (httpx.TimeoutException, httpx.ConnectTimeout):
        reasons.append(f"Connection timed out after {timeout} seconds.")
        return False, reasons
    except httpx.RequestError as exc:
        reasons.append(f"Network request error: {type(exc).__name__} - {str(exc)}")
        return False, reasons
    finally:
        if should_close_client:
            client.close()
