"""Unit tests for Evidence Verification (Anti-Hallucination Line of Defense).

Verifies:
- Authentic quotes are verified.
- Fabricated quotes cause the field to be nullified and marked 'unverified'.
- Whitespace and quote normalization works accurately.
- Missing evidence quotes trigger nullification.
"""

from utils.evidence_check import normalize_text, verify_evidence


def test_normalize_text_collapses_whitespace_and_unicode_quotes():
    """Ensure curly quotes, newlines, and non-breaking spaces are properly normalized."""
    raw = "  “Full   tuition\n\nand  monthly   stipend”\xa0of  $1000.  "
    expected = '"full tuition and monthly stipend" of $1000.'
    assert normalize_text(raw) == expected


def test_verify_evidence_accepts_grounded_fields():
    """Test that fields with quotes present in the text are retained and marked 'verified'."""
    page_text = """
    The Chevening Scholarship is the UK Government’s global scholarship programme.
    Deadline for applications is 5 November 2026.
    Funding covers full university tuition fees, a monthly living allowance, and travel costs.
    Applicants must have an undergraduate degree and at least two years of work experience.
    """

    extracted_fields = {
        "title": "Chevening Scholarships",
        "funding": "Full university tuition fees and monthly living allowance",
        "deadline": "2026-11-05",
        "description": "UK Government’s global scholarship programme",
    }

    evidence = {
        "title": "Chevening Scholarship",
        "funding": "full university tuition fees, a monthly living allowance",
        "deadline": "Deadline for applications is 5 November 2026",
        "description": "UK Government’s global scholarship programme",
    }

    sanitized, verifications = verify_evidence(extracted_fields, evidence, page_text)

    assert verifications["funding"] == "verified"
    assert sanitized["funding"] == extracted_fields["funding"]

    assert verifications["deadline"] == "verified"
    assert sanitized["deadline"] == "2026-11-05"

    assert verifications["description"] == "verified"


def test_verify_evidence_nullifies_hallucinated_or_missing_quotes():
    """Ensure that fabricated quotes cause the field to be nullified and marked 'unverified'."""
    page_text = """
    The scholarship covers tuition fees only. Accommodation is not included.
    Eligible candidates must be under 30 years of age.
    """

    extracted_fields = {
        "title": "State University Scholarship",
        "funding": "Full coverage including luxury accommodation and flights",  # Hallucinated!
        "eligibility": ["Must have TOEFL 100", "Under 30 years old"],
        "how_to_apply": "Submit via portal",  # No quote provided
    }

    evidence = {
        "title": "scholarship",
        "funding": "Free flights and 5-star accommodation provided to all fellows",  # Completely fabricated quote!
        "eligibility": "under 30 years of age",
        # 'how_to_apply' has NO evidence entry
    }

    sanitized, verifications = verify_evidence(extracted_fields, evidence, page_text)

    # 1. Hallucinated funding MUST be nullified
    assert sanitized["funding"] is None
    assert verifications["funding"] == "unverified"

    # 2. Missing evidence for how_to_apply MUST be nullified
    assert sanitized["how_to_apply"] is None
    assert verifications["how_to_apply"] == "unverified"

    # 3. Grounded eligibility quote is preserved
    assert verifications["eligibility"] == "verified"
    assert sanitized["eligibility"] is not None
