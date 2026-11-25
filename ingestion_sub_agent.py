"""Ingestion Sub-Agent (Task 2).

Transforms any official scholarship URL into a fully populated, grounded
draft Grant object ready for administrative review.

Key features:
1. SSRF-guarded page fetcher using shared url_guard and httpx.
2. Single-sublink crawler: Traverses 1 level depth within the same domain
   for eligibility/funding details.
3. Anti-hallucination verification: Verifies extracted quotes against page text.
4. Database persistence: Enforces DRAFT status and calculates content hash.
"""

import hashlib
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import httpx
from sqlalchemy.orm import Session
from core.db import get_db
from core.models import Grant, GrantStatus, YemeniEligibilityStatus
from core.repository import save_draft
from modules.matching.gpa import normalize_gpa_to_4
from modules.matching.nationalities import evaluate_nationality
from utils.evidence_check import verify_evidence
from utils.llm_extractor import GrantExtractionSchema, LLMClient, extract_grant_from_text
from utils.url_guard import ResolveFn, safe_request, validate_outbound_url
from utils.url_validator import is_trusted_domain, validate_official_url

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


def fetch_page(
    url: str,
    timeout: float = 15.0,
    *,
    client: Optional[httpx.Client] = None,
    resolve_fn: Optional[ResolveFn] = None,
    require_trusted_domain: bool = False,
) -> Tuple[str, List[Dict[str, str]]]:
    """Fetch webpage content safely through the SSRF guard and return clean text + links."""
    def _hop_check(hop_url: str) -> None:
        if require_trusted_domain:
            ok, reason = is_trusted_domain(hop_url)
            if not ok:
                raise ValueError(reason)

    result = safe_request(
        "GET",
        url,
        client=client,
        resolve_fn=resolve_fn,
        timeout=timeout,
        hop_validator=_hop_check if require_trusted_domain else None,
    )
    if result.status_code >= 400:
        req = httpx.Request("GET", result.final_url)
        resp = httpx.Response(result.status_code, request=req)
        raise httpx.HTTPStatusError(
            f"HTTP {result.status_code} while fetching {result.final_url}",
            request=req,
            response=resp,
        )
    return extract_text_and_links(result.text, base_url=result.final_url)


def extract_grant_preview(
    official_url: str,
    client: Optional[LLMClient] = None,
    page_html_override: Optional[str] = None,
    skip_url_validation: bool = False,
) -> Dict[str, Any]:
    """Fetch, validate, extract, and verify a scholarship URL WITHOUT saving to DB."""
    logger.info("Starting ingestion extraction for URL: %s", official_url)

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
        main_text, links = fetch_page(official_url, require_trusted_domain=not skip_url_validation)
        # 3. Follow at most one relevant sub-link (same domain, 1 level depth)
        sublink_url = find_relevant_sublink(official_url, links)

    combined_text = main_text

    # Crawl sublink if discovered
    if sublink_url:
        try:
            validate_outbound_url(sublink_url)
            logger.info("Found relevant sub-link: %s. Fetching additional criteria...", sublink_url)
            sub_text, _ = fetch_page(sublink_url, require_trusted_domain=not skip_url_validation)
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
        "provider_name": extraction.provider_name,
        "host_country": extraction.host_country,
        "allowed_degrees": extraction.allowed_degrees,
        "min_gpa_value": extraction.min_gpa_value,
        "min_gpa_scale": extraction.min_gpa_scale,
        "language_requirements": (
            [item.model_dump() for item in extraction.language_requirements]
            if extraction.language_requirements
            else None
        ),
        "nationality_rule": extraction.nationality_rule.model_dump(),
        "min_work_years": extraction.min_work_years,
        "max_age": extraction.max_age,
        "funding_type": extraction.funding_type,
    }

    # 6. Anti-hallucination verification: check evidence quotes in combined text
    sanitized_fields, field_verifications = verify_evidence(
        fields=raw_fields,
        evidence=extraction.evidence,
        page_text=combined_text,
    )

    # 7. Convert deadline to python date object ONLY if verified by evidence_check
    verified_deadline_raw = sanitized_fields.get("deadline")
    parsed_date = None
    if verified_deadline_raw:
        try:
            parsed_date = date.fromisoformat(str(verified_deadline_raw).strip())
        except (ValueError, TypeError):
            parsed_date = None

    verified_nat_rule = sanitized_fields.get("nationality_rule")
    yemen_status = sanitized_fields.get("accepts_yemeni") or "unclear"
    if (
        yemen_status == "unclear"
        and isinstance(verified_nat_rule, dict)
        and verified_nat_rule.get("mode") not in (None, "unclear")
    ):
        yemen_status = evaluate_nationality("YE", verified_nat_rule)

    min_gpa_value = sanitized_fields.get("min_gpa_value")
    min_gpa_scale = sanitized_fields.get("min_gpa_scale")
    normalized_gpa = normalize_gpa_to_4(min_gpa_value, min_gpa_scale)

    yemen_str = yemen_status.value if hasattr(yemen_status, "value") else str(yemen_status)

    return {
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
        "accepts_yemeni": yemen_str or "unclear",
        "provider_name": sanitized_fields.get("provider_name"),
        "host_country": sanitized_fields.get("host_country"),
        "allowed_degrees": sanitized_fields.get("allowed_degrees"),
        "min_gpa_value": min_gpa_value,
        "min_gpa_scale": min_gpa_scale,
        "min_gpa_normalized_4": normalized_gpa,
        "language_requirements": sanitized_fields.get("language_requirements"),
        "nationality_rule": verified_nat_rule,
        "min_work_years": sanitized_fields.get("min_work_years"),
        "max_age": sanitized_fields.get("max_age"),
        "funding_type": sanitized_fields.get("funding_type") or "unknown",
        "evidence": extraction.evidence or {},
        "field_verification": field_verifications,
        "content_hash": content_hash,
    }


def ingest(
    official_url: str,
    db: Optional[Session] = None,
    client: Optional[LLMClient] = None,
    page_html_override: Optional[str] = None,
    skip_url_validation: bool = False,
) -> Grant:
    """Ingest an official scholarship URL and convert it into a verified draft Grant."""
    grant_payload = extract_grant_preview(
        official_url,
        client=client,
        page_html_override=page_html_override,
        skip_url_validation=skip_url_validation,
    )

    if db is not None:
        return save_draft(db, grant_payload)
    with get_db() as session:
        return save_draft(session, grant_payload)
