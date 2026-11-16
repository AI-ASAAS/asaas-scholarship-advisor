"""Ingestion Sub-Agent (Task 2).

Transforms any official scholarship URL into a fully populated, grounded
draft Grant object ready for administrative review.

Key features:
1. Resilient page fetcher: Uses Playwright / httpx fallback.
2. Single-sublink crawler: Traverses 1 level depth within the same domain
   for eligibility/funding details.
3. Anti-hallucination verification: Verifies extracted quotes against page text.
4. Database persistence: Enforces DRAFT status and calculates content hash.
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import httpx
from sqlalchemy.orm import Session
from core.db import get_db
from core.models import Grant, GrantStatus, YemeniEligibilityStatus
from core.repository import save_draft
from utils.evidence_check import verify_evidence
from utils.llm_extractor import GrantExtractionSchema, LLMClient, extract_grant_from_text
from utils.url_validator import validate_official_url

logger = logging.getLogger(__name__)

# Keywords triggering a 1-level sub-page crawl
SUBLINK_KEYWORDS = [
    "eligibility",
    "criteria",
    "requirement",
    "funding",
    "financial",
    "benefit",
    "apply",
    "application",
    "how to apply",
    "admission",
    "guideline",
    "selection",
    # Arabic keywords
    "شروط",
    "معايير",
    "تمويل",
    "مزايا",
    "تقديم",
    "طريقة التقديم",
    "وثائق",
]


def compute_content_hash(text: str) -> str:
    """Calculate SHA-256 fingerprint of the page text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_text_and_links(html_content: str, base_url: str) -> Tuple[str, List[Dict[str, str]]]:
    """Parse HTML, strip irrelevant markup (scripts/styles/nav), and extract text & internal links."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "noscript", "svg", "footer", "nav", "header"]):
        tag.decompose()

    # Extract all links
    links: List[Dict[str, str]] = []
    base_host = (urlparse(base_url).hostname or "").lower()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        link_text = a_tag.get_text(separator=" ", strip=True)

        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue

        absolute_url = urljoin(base_url, href)
        link_host = (urlparse(absolute_url).hostname or "").lower()

        # Keep links belonging to the exact same domain
        if link_host == base_host:
            links.append({"url": absolute_url, "text": link_text})

    # Extract clean readable text
    body_text = soup.get_text(separator="\n", strip=True)
    return body_text, links


def find_relevant_sublink(base_url: str, links: List[Dict[str, str]]) -> Optional[str]:
    """Find at most ONE relevant sub-link matching eligibility/funding criteria on same domain."""
    normalized_base = base_url.rstrip("/").lower()
    base_host = (urlparse(base_url).hostname or "").lower()

    for item in links:
        url = item["url"]
        text = item["text"].lower()
        path = urlparse(url).path.lower()

        # Must not be the identical base URL
        if url.rstrip("/").lower() == normalized_base:
            continue

        # Must have same hostname
        if (urlparse(url).hostname or "").lower() != base_host:
            continue

        # Check if text or URL path matches any criteria keyword
        combined_text = f"{text} {path}"
        if any(kw in combined_text for kw in SUBLINK_KEYWORDS):
            return url

    return None


def fetch_page(url: str, timeout: float = 15.0) -> Tuple[str, List[Dict[str, str]]]:
    """Fetch webpage content and return clean text plus links."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 DiscoveryAgent/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return extract_text_and_links(response.text, base_url=str(response.url))


def ingest(
    official_url: str,
    db: Optional[Session] = None,
    client: Optional[LLMClient] = None,
    page_html_override: Optional[str] = None,
    skip_url_validation: bool = False,
) -> Grant:
    """Ingest an official scholarship URL and convert it into a verified draft Grant.

    Args:
        official_url: Verified official URL of the scholarship.
        db: Optional SQLAlchemy Session. If None, uses get_db() context.
        client: Optional LLMClient instance (can be mock or custom).
        page_html_override: Optional raw HTML string for offline unit testing without network.
        skip_url_validation: If True, bypasses network url_validator (useful for tests).

    Returns:
        Grant instance saved in DRAFT status.
    """
    logger.info("Starting ingestion for URL: %s", official_url)

    # 1. Official URL validation
    if not skip_url_validation:
        is_valid, reasons = validate_official_url(official_url)
        if not is_valid:
            error_msg = f"URL failed validation: {'; '.join(reasons)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    # 2. Fetch primary page
    sublink_url = None
    if page_html_override is not None:
        main_text, links = extract_text_and_links(page_html_override, base_url=official_url)
    else:
        main_text, links = fetch_page(official_url)
        # 3. Follow at most one relevant sub-link (same domain, 1 level depth)
        sublink_url = find_relevant_sublink(official_url, links)

    combined_text = main_text

    # Crawl sublink if discovered
    if sublink_url:
        try:
            logger.info("Found relevant sub-link: %s. Fetching additional criteria...", sublink_url)
            sub_text, _ = fetch_page(sublink_url)
            combined_text += f"\n\n--- ADDITIONAL DETAILS FROM SUB-PAGE ({sublink_url}) ---\n{sub_text}"
        except Exception as exc:
            logger.warning("Could not fetch sublink %s: %s", sublink_url, exc)

    # 4. Compute content fingerprint
    content_hash = compute_content_hash(combined_text)

    # 5. Extract structured data via LLM
    extraction: GrantExtractionSchema = extract_grant_from_text(combined_text, client=client)

    raw_fields = {
        "title": extraction.title,
        "description": extraction.description,
        "eligibility": extraction.eligibility,
        "criteria": extraction.criteria,
        "fields_of_study": extraction.fields_of_study,
        "funding": extraction.funding,
        "required_documents": extraction.required_documents,
        "deadline": extraction.deadline,
        "how_to_apply": extraction.how_to_apply,
        "accepts_yemeni": extraction.accepts_yemeni,
    }

    # 6. Anti-hallucination verification: check evidence quotes in combined text
    sanitized_fields, field_verifications = verify_evidence(
        fields=raw_fields,
        evidence=extraction.evidence,
        page_text=combined_text,
    )

    # 7. Convert deadline to python date object if present
    parsed_date = extraction.get_parsed_deadline()

    # 8. Prepare payload for repository
    grant_payload = {
        "title": sanitized_fields.get("title") or extraction.title or "Untitled Scholarship",
        "official_url": official_url,
        "description": sanitized_fields.get("description"),
        "eligibility": sanitized_fields.get("eligibility"),
        "criteria": sanitized_fields.get("criteria"),
        "fields_of_study": sanitized_fields.get("fields_of_study"),
        "funding": sanitized_fields.get("funding"),
        "required_documents": sanitized_fields.get("required_documents"),
        "deadline": parsed_date,
        "how_to_apply": sanitized_fields.get("how_to_apply"),
        "accepts_yemeni": sanitized_fields.get("accepts_yemeni") or YemeniEligibilityStatus.UNCLEAR,
        "evidence": extraction.evidence or {},
        "field_verification": field_verifications,
        "content_hash": content_hash,
    }

    # 9. Save as DRAFT in the database
    if db is not None:
        saved_grant = save_draft(db, grant_payload)
        return saved_grant
    else:
        with get_db() as session:
            saved_grant = save_draft(session, grant_payload)
            return saved_grant
