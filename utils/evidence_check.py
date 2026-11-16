"""Evidence verification module for anti-hallucination validation.

Guarantees that every extracted field is grounded in an exact, verifiable quote
from the fetched webpage text. If an extraction lacks valid grounding evidence,
the field is nullified to prevent hallucinations from entering the database.
"""

import re
import unicodedata
from typing import Any, Dict, Optional, Tuple


def normalize_text(text: Optional[str]) -> str:
    """Normalize text by collapsing whitespace, stripping unicode noise, and standardizing quotes."""
    if not text:
        return ""

    # Normalize unicode characters (NFKC)
    text = unicodedata.normalize("NFKC", text)

    # Standardize curly/smart quotes and special dashes to standard ASCII
    replacements = {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "«": '"',
        "»": '"',
        "—": "-",
        "–": "-",
        "\xa0": " ",  # Non-breaking space
        "\u200b": "",  # Zero-width space
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)

    # Collapse multiple whitespace characters (including newlines and tabs) to single spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def is_quote_in_text(quote: str, page_text: str) -> bool:
    """Check if a quote verbatim exists within the page text after normalization."""
    if not quote or not quote.strip():
        return False

    norm_quote = normalize_text(quote)
    norm_page = normalize_text(page_text)

    # If normalized quote is very short (less than 4 chars), require exact boundary or check
    if len(norm_quote) < 3:
        return False

    return norm_quote in norm_page


def verify_evidence(
    fields: Dict[str, Any],
    evidence: Dict[str, str],
    page_text: str,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Verify extracted fields against verbatim evidence quotes from the page text.

    Rules:
    1. If a field has a non-null value, it MUST have a matching quote in `evidence`.
    2. The quote must exist verbatim in `page_text` (normalized).
    3. If the quote is missing or not found in the text, the field is cleared to None
       (or empty list), and marked as 'unverified'.
    4. If the quote is verified in the text, the field is marked as 'verified'.

    Returns:
        (sanitized_fields, field_verification)
    """
    sanitized_fields = dict(fields)
    field_verification: Dict[str, str] = {}

    if not page_text:
        # If page_text is empty, all non-null fields fail verification
        for field, value in fields.items():
            if value is not None and value != [] and value != {}:
                sanitized_fields[field] = None if not isinstance(value, list) else None
                field_verification[field] = "unverified"
            else:
                field_verification[field] = "verified"
        return sanitized_fields, field_verification

    for field, value in fields.items():
        # Skip internal metadata fields
        if field in {"id", "official_url", "content_hash", "last_checked_at", "created_at", "updated_at", "status"}:
            continue

        # If field is already None or empty, it is considered naturally empty
        if value is None or (isinstance(value, (list, dict, str)) and len(value) == 0):
            field_verification[field] = "verified"
            continue

        # Special handling for accepts_yemeni
        if field == "accepts_yemeni":
            str_val = value.value if hasattr(value, "value") else str(value).lower()
            if str_val == "unclear":
                sanitized_fields[field] = "unclear"
                field_verification[field] = "verified"
                continue
            # For yes/no, check quote under accepts_yemeni or fallback to eligibility
            quote = evidence.get("accepts_yemeni") or evidence.get("eligibility")
            if quote and isinstance(quote, str) and is_quote_in_text(quote, page_text):
                sanitized_fields[field] = str_val
                field_verification[field] = "verified"
            else:
                sanitized_fields[field] = "unclear"
                field_verification[field] = "unverified"
            continue

        quote = evidence.get(field)

        if not quote or not isinstance(quote, str) or not quote.strip():
            # No evidence quote provided -> Nullify
            sanitized_fields[field] = None
            field_verification[field] = "unverified"
            continue

        if is_quote_in_text(quote, page_text):
            # Evidence verified in page text!
            field_verification[field] = "verified"
        else:
            # Fabricated / hallucinated quote not found in page text -> Nullify
            sanitized_fields[field] = None
            field_verification[field] = "unverified"

    return sanitized_fields, field_verification
