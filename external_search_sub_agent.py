"""External Deep Search Sub-Agent (Task 4 - ReAct Search Agent).

Autonomous search agent operating on the ReAct (Reason + Act) paradigm to discover
external scholarships tailored to a student's profile (major, degree level, target country)
and explicitly checking eligibility for Yemeni students.

Anti-hallucination guardrails:
1. Strict maximum of 5 ReAct steps.
2. Zero links from LLM memory: only URLs returned by the search tool are considered.
3. Mandatory page visit (fetch_page) and official URL validation before returning any result.
4. Explicit verbatim quote verification for both profile match and Yemeni eligibility.
5. Read-only: returns verified results for review; never writes directly to the database.
"""

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple
import httpx
from pydantic import BaseModel, Field

# Ensure project root is on sys.path for standalone CLI execution
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import settings
from ingestion_sub_agent import fetch_page
from utils.evidence_check import is_quote_in_text, normalize_text
from utils.url_validator import validate_official_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MAX_REACT_STEPS = 5


# ---------------------------------------------------------------------------
# Pydantic Contracts
# ---------------------------------------------------------------------------

class StudentProfile(BaseModel):
    """Input profile describing the Yemeni student seeking scholarships."""
    major: str = Field(..., min_length=2, description="Field of study or academic major (e.g., Computer Science).")
    degree_level: str = Field(..., min_length=2, description="Target degree (e.g., Bachelor, Master, PhD).")
    target_country: Optional[str] = Field(default=None, description="Optional target country (e.g., Germany, UK).")


class VerifiedScholarshipResult(BaseModel):
    """A single externally discovered and code-verified scholarship result."""
    title: str
    official_url: str
    match_reason: str
    evidence_quote: str
    accepts_yemeni: Literal["yes", "no", "unclear"]
    yemen_evidence: Optional[str] = None


class ReActStep(BaseModel):
    """Structured audit log entry for a single Thought / Action / Observation cycle."""
    step_number: int
    thought: str
    action: str
    action_input: Dict[str, Any] = Field(default_factory=dict)
    observation: str


class SearchAgentOutput(BaseModel):
    """Final structured output of the External Search Sub-Agent."""
    student_profile: StudentProfile
    results: List[VerifiedScholarshipResult] = Field(default_factory=list)
    reason: str
    steps_taken: int
    trace: List[ReActStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent Tools
# ---------------------------------------------------------------------------

def search_web(query: str, max_results: int = 5, timeout: float = 15.0) -> List[Dict[str, str]]:
    """Search the web using Tavily API (primary) or Serper API (fallback).

    Returns a list of dicts: [{"title": str, "url": str, "snippet": str}]
    """
    if settings.TAVILY_API_KEY:
        logger.info("Executing Tavily search: %s", query)
        payload = {
            "api_key": settings.TAVILY_API_KEY,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": item.get("title", "Untitled"),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                }
                for item in data.get("results", [])
                if item.get("url")
            ]

    if settings.SERPER_API_KEY:
        logger.info("Executing Serper search: %s", query)
        headers = {
            "X-API-KEY": settings.SERPER_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": max_results}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post("https://google.serper.dev/search", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": item.get("title", "Untitled"),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
                for item in data.get("organic", [])
                if item.get("link")
            ]

    raise RuntimeError(
        "No external search API key configured. Please set TAVILY_API_KEY or SERPER_API_KEY in .env."
    )


def _split_sentences(text: str) -> List[str]:
    """Split text into clean, readable sentences for verbatim evidence extraction."""
    raw_chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [chunk.strip() for chunk in raw_chunks if len(chunk.strip()) >= 10]


def check_yemen_eligibility(text: str) -> Tuple[Literal["yes", "no", "unclear"], Optional[str]]:
    """Determine Yemeni student eligibility strictly from explicit statements in page text.

    Rules:
    - 'no': Explicit exclusion of Yemen OR explicit restriction excluding Yemen
            (e.g., 'EU citizens only', 'US citizens only', 'domestic students only').
    - 'yes': Explicit mention of Yemen/Yemeni as eligible OR explicit universal eligibility
             ('all nationalities', 'all developing countries', 'citizens of all countries').
    - 'unclear': Default whenever no explicit textual proof exists.

    Returns:
        (status, verbatim_quote_or_None)
    """
    if not text or not text.strip():
        return "unclear", None

    sentences = _split_sentences(text)

    # 1. Check explicit exclusions first
    exclusion_patterns = [
        r"\b(exclude|excluded|not eligible|ineligible)\b.*\byemen",
        r"\byemen\b.*\b(excluded|not eligible|ineligible|prohibited)\b",
        r"\b(eu|european union|u\.?s\.?|united states|uk|british|canadian|australian|domestic)\s+(citizens|nationals|students|residents)\s+only\b",
        r"\bonly\s+(open\s+to\s+)?(eu|european union|u\.?s\.?|united states|domestic)\s+(citizens|nationals|students)\b",
        r"\bcommonwealth\s+citizens\s+only\b",
        r"\basean\s+(citizens|nationals|countries)\s+only\b",
        r"غير مؤهل.*اليمن|يستثنى.*اليمن",
    ]
    for sentence in sentences:
        norm_s = normalize_text(sentence)
        for pattern in exclusion_patterns:
            if re.search(pattern, norm_s):
                return "no", sentence

    # 2. Check explicit inclusions
    inclusion_patterns = [
        r"\byemen(i|is)?\b",
        r"\ball\s+nationalities\b",
        r"\bcitizens\s+of\s+all\s+countries\b",
        r"\bopen\s+to\s+(all\s+)?international\s+students\b",
        r"\b(all\s+)?developing\s+(countries|nations)\b",
        r"\bglobal\s+scholarship\b",
        r"\bstudents\s+from\s+any\s+country\b",
        r"الطلاب اليمنيين|مواطني اليمن|اليمن|جميع الجنسيات|الدول النامية",
    ]
    for sentence in sentences:
        norm_s = normalize_text(sentence)
        for pattern in inclusion_patterns:
            if re.search(pattern, norm_s):
                return "yes", sentence

    # 3. Default to unclear (no guessing)
    return "unclear", None


def find_profile_match_evidence(text: str, profile: StudentProfile) -> Tuple[Optional[str], Optional[str]]:
    """Find a verbatim quote in page text proving relevance to the student's major/degree.

    Returns:
        (match_reason, verbatim_quote) or (None, None) if not grounded in page text.
    """
    if not text:
        return None, None

    sentences = _split_sentences(text)
    major_lower = profile.major.lower().strip()
    degree_lower = profile.degree_level.lower().strip()

    # Map common degree synonyms for accurate matching
    degree_synonyms = {
        "bachelor": ["bachelor", "undergraduate", "bsc", "ba", "بكالوريوس"],
        "master": ["master", "postgraduate", "graduate", "msc", "ma", "ماجستير"],
        "phd": ["phd", "doctoral", "doctorate", "postgraduate", "دكتوراه"],
    }
    degree_terms = degree_synonyms.get(degree_lower, [degree_lower])

    major_quote = None
    degree_quote = None
    broad_field_quote = None

    for sentence in sentences:
        norm_s = normalize_text(sentence)
        if not major_quote and major_lower in norm_s:
            major_quote = sentence
        if not degree_quote and any(term in norm_s for term in degree_terms):
            degree_quote = sentence
        if not broad_field_quote and re.search(r"\b(all\s+(academic\s+)?fields|any\s+field|all\s+disciplines|all\s+majors|جميع التخصصات)\b", norm_s):
            broad_field_quote = sentence

    if major_quote and is_quote_in_text(major_quote, text):
        reason = f"Matches requested major '{profile.major}'"
        if degree_quote:
            reason += f" and degree level '{profile.degree_level}'"
        return reason, major_quote

    if broad_field_quote and is_quote_in_text(broad_field_quote, text):
        reason = f"Open to all academic fields (covers '{profile.major}')"
        if degree_quote:
            reason += f" for '{profile.degree_level}'"
        return reason, broad_field_quote

    if degree_quote and is_quote_in_text(degree_quote, text):
        return f"Matches requested degree level '{profile.degree_level}'", degree_quote

    return None, None


# ---------------------------------------------------------------------------
# ReAct External Search Sub-Agent
# ---------------------------------------------------------------------------

class ExternalSearchAgent:
    """Bounded ReAct agent (max 5 steps) for verified external scholarship discovery."""

    def __init__(
        self,
        max_steps: int = MAX_REACT_STEPS,
        search_fn: Optional[Callable[[str, int], List[Dict[str, str]]]] = None,
        fetch_fn: Optional[Callable[[str], Tuple[str, List[Dict[str, str]]]]] = None,
        validate_fn: Optional[Callable[[str, Optional[str]], Tuple[bool, List[str]]]] = None,
    ):
        self.max_steps = min(max_steps, MAX_REACT_STEPS)
        self.search_fn = search_fn or search_web
        self.fetch_fn = fetch_fn or fetch_page
        self.validate_fn = validate_fn or validate_official_url

    def _build_query(self, profile: StudentProfile) -> str:
        """Construct a targeted official scholarship search query from the student profile."""
        parts = [
            f"official {profile.degree_level} scholarship",
            profile.major,
            "international students Yemen",
        ]
        if profile.target_country:
            parts.append(profile.target_country)
        return " ".join(parts)

    def run(self, profile: StudentProfile, max_verified_results: int = 3) -> SearchAgentOutput:
        """Execute the ReAct Thought -> Action -> Observation loop within strict step budget."""
        trace: List[ReActStep] = []
        verified_results: List[VerifiedScholarshipResult] = []
        visited_urls: Set[str] = set()
        validated_urls: Set[str] = set()
        step_num = 0

        # ---- STEP 1: Formulate query & run external search ----
        step_num += 1
        query = self._build_query(profile)
        thought_1 = (
            f"I need to find official {profile.degree_level} scholarships in {profile.major}"
            + (f" in {profile.target_country}" if profile.target_country else "")
            + " that accept Yemeni students. I will search using the search tool first."
        )
        logger.info("[Step %d/%d] Thought: %s", step_num, self.max_steps, thought_1)

        try:
            candidates = self.search_fn(query, 5)
            obs_1 = f"Search returned {len(candidates)} candidate URLs."
        except Exception as exc:
            obs_1 = f"Search tool error: {exc}"
            trace.append(
                ReActStep(
                    step_number=step_num,
                    thought=thought_1,
                    action="search",
                    action_input={"query": query},
                    observation=obs_1,
                )
            )
            return SearchAgentOutput(
                student_profile=profile,
                results=[],
                reason=f"External search failed: {exc}",
                steps_taken=step_num,
                trace=trace,
            )

        trace.append(
            ReActStep(
                step_number=step_num,
                thought=thought_1,
                action="search",
                action_input={"query": query},
                observation=obs_1,
            )
        )

        if not candidates:
            return SearchAgentOutput(
                student_profile=profile,
                results=[],
                reason="Search engine returned no candidate scholarships for the given profile.",
                steps_taken=step_num,
                trace=trace,
            )

        # ---- STEPS 2..MAX_STEPS: Validate, Visit, and Verify Candidates ----
        for candidate in candidates:
            if step_num >= self.max_steps:
                logger.info("Reached strict ReAct step limit (%d). Stopping.", self.max_steps)
                break
            if len(verified_results) >= max_verified_results:
                break

            url = candidate.get("url", "").strip()
            title = candidate.get("title", "Untitled Scholarship").strip()
            if not url or url in visited_urls:
                continue

            step_num += 1
            thought = (
                f"Candidate '{title}' ({url}) returned by search. "
                "I must validate it is an official live domain, fetch its page text, "
                "verify profile match, and explicitly check Yemeni student eligibility."
            )
            logger.info("[Step %d/%d] Thought: %s", step_num, self.max_steps, thought)

            # Action A: Validate official URL
            is_valid, reasons = self.validate_fn(url, title)
            if not is_valid:
                obs = f"REJECTED by validate_official_url: {'; '.join(reasons)}"
                logger.info("[Step %d/%d] Observation: %s", step_num, self.max_steps, obs)
                trace.append(
                    ReActStep(
                        step_number=step_num,
                        thought=thought,
                        action="validate_official_url",
                        action_input={"url": url, "grant_name": title},
                        observation=obs,
                    )
                )
                continue

            validated_urls.add(url)

            # Action B: Fetch actual page content (mandatory visit)
            try:
                page_text, _ = self.fetch_fn(url)
                visited_urls.add(url)
            except Exception as exc:
                obs = f"Failed to fetch page content from {url}: {exc}"
                logger.warning("[Step %d/%d] Observation: %s", step_num, self.max_steps, obs)
                trace.append(
                    ReActStep(
                        step_number=step_num,
                        thought=thought,
                        action="fetch_page",
                        action_input={"url": url},
                        observation=obs,
                    )
                )
                continue

            # Action C: Check Yemeni eligibility strictly from fetched page text
            yemen_status, yemen_quote = check_yemen_eligibility(page_text)
            if yemen_status == "no":
                obs = f"REJECTED: Page explicitly excludes Yemeni students. Quote: '{yemen_quote}'"
                logger.info("[Step %d/%d] Observation: %s", step_num, self.max_steps, obs)
                trace.append(
                    ReActStep(
                        step_number=step_num,
                        thought=thought,
                        action="check_yemen_eligibility",
                        action_input={"url": url},
                        observation=obs,
                    )
                )
                continue

            # Action D: Verify profile match with verbatim evidence quote
            match_reason, match_quote = find_profile_match_evidence(page_text, profile)
            if not match_reason or not match_quote:
                obs = (
                    f"SKIPPED: Official page was visited, but contained no grounded text matching "
                    f"major '{profile.major}' or degree '{profile.degree_level}'."
                )
                logger.info("[Step %d/%d] Observation: %s", step_num, self.max_steps, obs)
                trace.append(
                    ReActStep(
                        step_number=step_num,
                        thought=thought,
                        action="fetch_page+verify_match",
                        action_input={"url": url},
                        observation=obs,
                    )
                )
                continue

            # Final programmatic grounding gate (belt-and-suspenders anti-hallucination check)
            if url in visited_urls and url in validated_urls and is_quote_in_text(match_quote, page_text):
                verified_item = VerifiedScholarshipResult(
                    title=title,
                    official_url=url,
                    match_reason=match_reason,
                    evidence_quote=match_quote,
                    accepts_yemeni=yemen_status,
                    yemen_evidence=yemen_quote,
                )
                verified_results.append(verified_item)
                obs = (
                    f"VERIFIED & ACCEPTED: '{title}' | accepts_yemeni={yemen_status} | "
                    f"match='{match_reason}'"
                )
                logger.info("[Step %d/%d] Observation: %s", step_num, self.max_steps, obs)
                trace.append(
                    ReActStep(
                        step_number=step_num,
                        thought=thought,
                        action="fetch_page+validate+check_yemen_eligibility",
                        action_input={"url": url},
                        observation=obs,
                    )
                )

        if verified_results:
            summary_reason = (
                f"Found {len(verified_results)} verified official scholarship(s) matching "
                f"{profile.degree_level} in {profile.major} within {step_num} steps."
            )
        else:
            summary_reason = (
                f"No verified official scholarships matched the student profile after {step_num} steps. "
                "All candidates were either non-official, unreachable, excluded Yemen, or lacked grounded match evidence."
            )

        return SearchAgentOutput(
            student_profile=profile,
            results=verified_results,
            reason=summary_reason,
            steps_taken=step_num,
            trace=trace,
        )


def search_external_scholarships(
    major: str,
    degree_level: str,
    target_country: Optional[str] = None,
    max_steps: int = MAX_REACT_STEPS,
) -> SearchAgentOutput:
    """Convenience entry point for running the External ReAct Search Sub-Agent."""
    profile = StudentProfile(
        major=major,
        degree_level=degree_level,
        target_country=target_country,
    )
    agent = ExternalSearchAgent(max_steps=max_steps)
    return agent.run(profile)


def main():
    parser = argparse.ArgumentParser(description="External ReAct Deep Search Sub-Agent (Task 4).")
    parser.add_argument("--major", required=True, help="Student academic major (e.g., 'Computer Science').")
    parser.add_argument("--degree", required=True, help="Target degree level (e.g., 'Master').")
    parser.add_argument("--country", default=None, help="Optional target country (e.g., 'Germany').")
    args = parser.parse_args()

    output = search_external_scholarships(
        major=args.major,
        degree_level=args.degree,
        target_country=args.country,
    )

    print("\n" + "=" * 80)
    print(f"EXTERNAL SEARCH AGENT REPORT ({output.steps_taken} steps)")
    print("=" * 80)
    print(f"Reason: {output.reason}\n")
    for idx, res in enumerate(output.results, 1):
        print(f"{idx}. {res.title}")
        print(f"   URL: {res.official_url}")
        print(f"   Accepts Yemeni: {res.accepts_yemeni.upper()} | Evidence: {res.yemen_evidence}")
        print(f"   Match Reason: {res.match_reason}")
        print(f"   Quote: \"{res.evidence_quote}\"\n")
    print("=" * 80)


if __name__ == "__main__":
    main()
