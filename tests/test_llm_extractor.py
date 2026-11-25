"""Unit tests for LLM Extractor module.

Verifies:
- Prompt template loading and version tracking.
- Pydantic schema validation and deadline date parsing.
- JSON markdown fence stripping.
"""

from datetime import date
import pytest
from utils.llm_extractor import (
    GrantExtractionSchema,
    LLMClient,
    load_prompt,
)


def test_load_prompt_loads_version_and_content():
    """Ensure prompt is loaded with its version tag and untrusted data boundary."""
    content, version = load_prompt("extraction")
    assert version == "extraction@2.0"
    assert "STRICT ANTI-HALLUCINATION RULES" in content
    assert "nationality_rule" in content
    assert "<SOURCE_PAGE>" in content


def test_grant_extraction_schema_validation():
    """Ensure GrantExtractionSchema correctly parses valid payloads and handles dates."""
    data = {
        "title": "DAAD Helmut-Schmidt-Programme",
        "funding": "Full scholarship with €934 monthly allowance",
        "deadline": "2026-07-31",
        "accepts_yemeni": "yes",
        "evidence": {
            "title": "Helmut-Schmidt-Programme",
            "deadline": "Deadline is 31 July 2026",
        },
    }
    schema = GrantExtractionSchema.model_validate(data)
    assert schema.title == "DAAD Helmut-Schmidt-Programme"
    assert schema.get_parsed_deadline() == date(2026, 7, 31)
    assert schema.accepts_yemeni == "yes"


def test_grant_extraction_schema_handles_invalid_or_null_dates():
    """Ensure non-ISO or null dates do not crash get_parsed_deadline."""
    schema = GrantExtractionSchema(title="Rolling Scholarship", deadline="rolling-basis")
    assert schema.get_parsed_deadline() is None

    schema_null = GrantExtractionSchema(title="No Deadline Scholarship", deadline=None)
    assert schema_null.get_parsed_deadline() is None


def test_llm_client_clean_json_markdown():
    """Ensure code blocks like ```json ... ``` are cleanly unwrapped."""
    client = LLMClient()
    raw = "```json\n{\"title\": \"Test Grant\"}\n```"
    cleaned = client._clean_json_markdown(raw)
    assert cleaned == '{"title": "Test Grant"}'
