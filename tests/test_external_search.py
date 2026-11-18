"""Unit tests for External Deep Search Sub-Agent (Task 4 - ReAct Agent).

Verifies:
- Rejection of fake, unreachable, or unofficial aggregator URLs.
- Strict adherence to the 5-step maximum ReAct budget.
- Mandatory page visit before returning any result.
- Explicit Yemen eligibility checking (yes / no / unclear) based solely on page text.
- Returning empty results with a clear reason when no verified match exists.
- Full Thought / Action / Observation step trace logging.
"""

import pytest
from external_search_sub_agent import (
    ExternalSearchAgent,
    MAX_REACT_STEPS,
    StudentProfile,
    check_yemen_eligibility,
)
from utils.url_validator import is_trusted_domain


def test_check_yemen_eligibility_explicit_yes_no_unclear():
    """Verify strict explicit rules for Yemeni student eligibility."""
    # 1. Explicit Yemen mention -> yes
    text_yes = "This fellowship is open to citizens of developing nations including Yemen."
    status, quote = check_yemen_eligibility(text_yes)
    assert status == "yes"
    assert quote is not None and "Yemen" in quote

    # 2. Universal international eligibility -> yes
    text_all = "Master scholarships are open to all nationalities worldwide."
    status_all, quote_all = check_yemen_eligibility(text_all)
    assert status_all == "yes"
    assert quote_all is not None

    # 3. Explicit restriction excluding Yemen -> no
    text_no = "Applicants must be EU citizens only to qualify for this funding."
    status_no, quote_no = check_yemen_eligibility(text_no)
    assert status_no == "no"
    assert quote_no is not None

    # 4. No explicit statement -> unclear (never guess!)
    text_unclear = "Applicants must submit a CV, two recommendation letters, and a research proposal."
    status_unclear, quote_unclear = check_yemen_eligibility(text_unclear)
    assert status_unclear == "unclear"
    assert quote_unclear is None


def test_react_agent_rejects_unofficial_and_returns_verified_results():
    """Test ReAct loop with mock search: rejects aggregator/excluded, accepts verified official."""
    profile = StudentProfile(
        major="Computer Science",
        degree_level="Master",
        target_country="Germany",
    )

    mock_search_results = [
        # 1. Spam aggregator (MUST be rejected by validate_official_url)
        {
            "title": "Free Germany Grant",
            "url": "https://scholarship-positions.com/germany-cs-grant",
            "snippet": "Apply now!",
        },
        # 2. Official domain, but explicitly excludes Yemen (EU citizens only)
        {
            "title": "EU Domestic Tech Grant",
            "url": "https://www.daad.de/eu-only-grant",
            "snippet": "Computer Science Master grant.",
        },
        # 3. Official domain, matches Computer Science + Master + accepts Yemen -> ACCEPTED!
        {
            "title": "DAAD Postgraduate Computer Science Scholarship",
            "url": "https://www.daad.de/en/cs-master-scholarship",
            "snippet": "Master scholarship in Germany.",
        },
    ]

    mock_pages = {
        "https://www.daad.de/eu-only-grant": (
            "The EU Domestic Tech Grant funds Master studies in Computer Science. "
            "Funding is restricted to EU citizens only.",
            [],
        ),
        "https://www.daad.de/en/cs-master-scholarship": (
            "DAAD Postgraduate Computer Science Scholarship. "
            "This Master programme supports Computer Science and AI research in Germany. "
            "Graduates from all developing countries including Yemen are eligible to apply.",
            [],
        ),
    }

    visited_by_mock = []

    def mock_search(query: str, max_results: int):
        return mock_search_results

    def mock_validate(url: str, name=None):
        ok, msg = is_trusted_domain(url)
        return ok, [msg]

    def mock_fetch(url: str):
        visited_by_mock.append(url)
        return mock_pages[url]

    agent = ExternalSearchAgent(
        max_steps=5,
        search_fn=mock_search,
        fetch_fn=mock_fetch,
        validate_fn=mock_validate,
    )

    output = agent.run(profile)

    # Assertions
    assert output.steps_taken <= MAX_REACT_STEPS
    assert len(output.results) == 1

    winner = output.results[0]
    assert winner.official_url == "https://www.daad.de/en/cs-master-scholarship"
    assert winner.official_url in visited_by_mock  # Must have actually visited the page!
    assert winner.accepts_yemeni == "yes"
    assert "Computer Science" in winner.evidence_quote
    assert "Yemen" in (winner.yemen_evidence or "")

    # Ensure aggregator was never even fetched
    assert "https://scholarship-positions.com/germany-cs-grant" not in visited_by_mock

    # Ensure every step was logged in trace
    assert len(output.trace) == output.steps_taken
    assert output.trace[0].action == "search"


def test_react_agent_strictly_respects_5_step_limit():
    """Ensure agent never exceeds 5 steps even when given 10 candidate URLs."""
    profile = StudentProfile(major="Medicine", degree_level="PhD")

    many_candidates = [
        {"title": f"Fake Grant {i}", "url": f"https://random-fake-{i}.xyz/grant", "snippet": "..."}
        for i in range(10)
    ]

    agent = ExternalSearchAgent(
        max_steps=5,
        search_fn=lambda q, m: many_candidates,
        fetch_fn=lambda u: ("", []),
        validate_fn=lambda u, n=None: (False, ["Untrusted domain"]),
    )

    output = agent.run(profile)

    assert output.steps_taken == 5
    assert len(output.trace) == 5
    assert output.results == []
    assert "لم تُعثر على منح رسمية مطابقة" in output.reason


def test_react_agent_returns_empty_list_with_reason_when_no_results():
    """Ensure clean empty list with reason when search yields nothing."""
    profile = StudentProfile(major="Quantum Archaeology", degree_level="PhD")

    agent = ExternalSearchAgent(
        search_fn=lambda q, m: [],
        fetch_fn=lambda u: ("", []),
        validate_fn=lambda u, n=None: (True, ["OK"]),
    )

    output = agent.run(profile)

    assert output.results == []
    assert output.steps_taken == 1
    assert "لا توجد نتائج مطابقة" in output.reason
