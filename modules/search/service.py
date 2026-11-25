"""Bounded profile-aware external scholarship search pipeline (Spec Task 4, D10)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple
from urllib.parse import urlparse

from core.config import settings
from core.db import get_db
from core.models import Grant, GrantStatus
from core.repository import save_draft
from external_search_sub_agent import (
    StudentProfile as LegacyStudentProfile,
    check_yemen_eligibility,
    find_profile_match_evidence,
    search_web,
)
from ingestion_sub_agent import compute_content_hash, fetch_page
from modules.llm.client import AsyncLLMClient, LLMError
from modules.llm.prompts import load_prompt
from modules.matching.gpa import normalize_student_gpa
from modules.matching.nationalities import evaluate_nationality, normalize_country_code
from modules.matching.service import evaluate_grant_for_student
from modules.search.repository import (
    SearchCacheRepository,
    make_page_cache_key,
    make_profile_cache_key,
)
from modules.search.schemas import (
    ExternalSearchCandidateResult,
    ExternalSearchRunRequest,
    ExternalSearchRunResponse,
    ExternalSearchStepLog,
    PromoteExternalGrantRequest,
    SearchQueryPlanLLM,
)
from utils.evidence_check import is_quote_in_text, normalize_text, verify_evidence
from utils.llm_extractor import GrantExtractionSchema, extract_grant_from_text_async
from utils.url_guard import UnsafeURLError
from utils.url_validator import validate_official_url

logger = logging.getLogger(__name__)

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_BUDGETS: Dict[str, Tuple["SearchRunBudget", Optional[str]]] = {}

_TITLE_STOPWORDS = {
    "scholarship",
    "scholarships",
    "program",
    "programme",
    "fellowship",
    "fellowships",
    "grant",
    "grants",
    "international",
    "students",
    "student",
    "for",
    "the",
    "and",
    "of",
    "in",
    "state",
    "government",
}


def _normalize_external_url(url: str) -> Tuple[str, str, str]:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/").lower()
    return host, path, f"{host}{path}"


def _distinctive_title_tokens(title: str) -> Set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9\u0600-\u06ff]+", (title or "").lower())
        if len(tok) > 2 and tok not in _TITLE_STOPWORDS
    }


def _load_platform_grants_index() -> Tuple[List[Dict[str, Any]], str]:
    """Load published ASAAS grants to avoid returning duplicates in outside-ASAAS search."""
    entries: List[Dict[str, Any]] = []
    finger_parts: List[str] = []
    with get_db() as db:
        rows = (
            db.query(Grant.title, Grant.official_url)
            .filter(Grant.status == GrantStatus.PUBLISHED)
            .all()
        )
        for title, official_url in rows:
            host, path, full = _normalize_external_url(official_url or "")
            tokens = _distinctive_title_tokens(title or "")
            entries.append(
                {
                    "title": title or "",
                    "host": host,
                    "path": path,
                    "full": full,
                    "tokens": tokens,
                }
            )
            finger_parts.append(f"{full}|{(title or '').strip().lower()}")
    fingerprint = hashlib.sha256("\n".join(sorted(finger_parts)).encode("utf-8")).hexdigest()[:16]
    return entries, fingerprint


def _matches_platform_grant(url: str, title: str, platform_entries: List[Dict[str, Any]]) -> bool:
    if not platform_entries:
        return False
    c_host, _c_path, c_full = _normalize_external_url(url)
    c_tokens = _distinctive_title_tokens(title)
    for entry in platform_entries:
        p_full = entry["full"]
        p_host = entry["host"]
        p_path = entry["path"]
        p_tokens = entry["tokens"]
        if c_full and p_full:
            if c_full == p_full:
                return True
            if c_host == p_host and p_path and (c_full.startswith(p_full + "/") or p_full.startswith(c_full + "/")):
                return True
        if c_tokens and p_tokens:
            overlap = len(c_tokens & p_tokens)
            min_len = min(len(c_tokens), len(p_tokens))
            if c_host and p_host and c_host == p_host and overlap >= 1 and (overlap / min_len) >= 0.6:
                return True
            if min_len >= 2 and (overlap / min_len) >= 0.8:
                return True
    return False


def cancel_active_run(run_id: str, session_id: Optional[str] = None) -> bool:
    with _ACTIVE_LOCK:
        entry = _ACTIVE_BUDGETS.get(run_id)
        if entry is None:
            return False
        budget, owner_sid = entry
        if owner_sid is not None and session_id != owner_sid:
            return False
        budget.cancelled = True
        return True


@dataclass
class SearchRunBudget:
    """Enforces wall-clock, query, page, step, and token caps (including retries)."""

    max_queries: int
    max_pages: int
    max_steps: int
    wall_clock_seconds: float
    max_tokens: int
    started_monotonic: float = field(default_factory=time.perf_counter)
    queries_used: int = 0
    pages_fetched: int = 0
    steps_taken: int = 0
    tokens_used: int = 0
    cancelled: bool = False

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started_monotonic) * 1000)

    def remaining_seconds(self) -> float:
        return max(0.0, self.wall_clock_seconds - (time.perf_counter() - self.started_monotonic))

    def stop_reason(self) -> Optional[Tuple[str, str]]:
        if self.cancelled:
            return ("تم إيقاف البحث بناءً على طلب المستخدم.", "Search cancelled by user request.")
        if (time.perf_counter() - self.started_monotonic) >= self.wall_clock_seconds:
            return (
                f"تم التوقف عند انتهاء المهلة الزمنية ({int(self.wall_clock_seconds)} ثانية).",
                f"Stopped cleanly at wall-clock limit ({int(self.wall_clock_seconds)}s).",
            )
        if self.steps_taken >= self.max_steps:
            return (
                f"تم التوقف عند الحد الأقصى للخطوات ({self.max_steps}).",
                f"Stopped at step limit ({self.max_steps}).",
            )
        if self.pages_fetched >= self.max_pages:
            return (
                f"تم التوقف عند الحد الأقصى للصفحات المفحوصة ({self.max_pages}).",
                f"Stopped at max fetched pages budget ({self.max_pages}).",
            )
        if self.tokens_used >= self.max_tokens:
            return (
                f"تم التوقف عند استهلاك سقف الرموز ({self.max_tokens}).",
                f"Stopped at token budget ({self.max_tokens}).",
            )
        return None


def check_generic_nationality_eligibility(
    text: str, nationality: str
) -> Tuple[Dict[str, Any], Literal_verdict, Optional[str]]:
    """Determine nationality rule & eligibility verdict generically from page text."""
    nat = normalize_country_code(nationality) or (nationality or "YE").upper().strip()
    if nat == "YE":
        verdict, quote = check_yemen_eligibility(text)
        if verdict == "yes":
            norm_q = normalize_text(quote or "")
            if any(k in norm_q for k in ("all nationalities", "all countries", "جميع الجنسيات", "developing countries")):
                rule = {"mode": "all", "countries": [], "groups": []}
            else:
                rule = {"mode": "include", "countries": ["YE"], "groups": []}
        elif verdict == "no":
            rule = {"mode": "exclude", "countries": ["YE"], "groups": []}
        else:
            rule = {"mode": "unclear", "countries": [], "groups": []}
        return rule, verdict, quote

    if not text or not text.strip():
        return {"mode": "unclear", "countries": [], "groups": []}, "unclear", None

    # Generic check for non-Yemeni nationality statements
    country_names = {
        "SD": ["sudan", "sudanese", "السودان", "سوداني"],
        "EG": ["egypt", "egyptian", "مصر", "مصري"],
        "JO": ["jordan", "jordanian", "الأردن", "أردني"],
        "SY": ["syria", "syrian", "سوريا", "سوري"],
        "PS": ["palestine", "palestinian", "فلسطين", "فلسطيني"],
        "IQ": ["iraq", "iraqi", "العراق", "عراقي"],
        "MA": ["morocco", "moroccan", "المغرب", "مغربي"],
        "TN": ["tunisia", "tunisian", "تونس", "تونسي"],
    }
    aliases = country_names.get(nat, [nat.lower()])
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) >= 8]
    for s in sentences:
        ns = normalize_text(s)
        if any(a in ns for a in aliases) and re.search(r"\b(exclude|excluded|not eligible|ineligible)\b|مستثنى|غير مؤهل", ns):
            return {"mode": "exclude", "countries": [nat], "groups": []}, "no", s
    for s in sentences:
        ns = normalize_text(s)
        if re.search(r"\b(all nationalities|citizens of all countries|open to international students|students from any country)\b|جميع الجنسيات", ns):
            return {"mode": "all", "countries": [], "groups": []}, "yes", s
        if any(a in ns for a in aliases):
            return {"mode": "include", "countries": [nat], "groups": []}, "yes", s
    return {"mode": "unclear", "countries": [], "groups": []}, "unclear", None


Literal_verdict = Any


def _deterministic_queries(req: ExternalSearchRunRequest) -> List[str]:
    countries = " OR ".join(req.target_countries[:3]) if req.target_countries else ""
    fields_part = req.target_fields[0] if req.target_fields else req.major
    base_q = f"{req.target_degree} scholarship {req.major} international students {countries} site:.org OR site:.gov OR site:.edu".strip()
    alt_q = f"{req.target_degree} fellowship {fields_part} {req.nationality} eligible official apply".strip()
    queries = [re.sub(r"\s+", " ", base_q), re.sub(r"\s+", " ", alt_q)]
    return queries[: max(1, settings.SEARCH_MAX_QUERIES)]


def _deterministic_extract_verified(
    *,
    url: str,
    title: str,
    page_text: str,
    req: ExternalSearchRunRequest,
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, str]]:
    """Fallback grounded extractor using verbatim sentences when LLM is unconfigured or capped."""
    _INJECTION_RE = re.compile(
        r"(ignore\s+(all\s+)?previous\s+instructions|disregard\s+(all\s+)?previous|system\s+prompt|overwrite\s+title|jailbreak)",
        re.IGNORECASE,
    )
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\n+", page_text)
        if len(s.strip()) >= 8 and not _INJECTION_RE.search(s)
    ]
    clean_text = "\n".join(sentences)
    norm_nat = normalize_country_code(req.nationality) or (req.nationality or "YE").upper().strip()
    nat_rule, _verdict, nat_quote = check_generic_nationality_eligibility(clean_text, norm_nat)

    deadline_val = None
    deadline_q = None
    for s in sentences:
        m = re.search(r"\b(202[5-9]-\d{2}-\d{2})\b", s)
        if m:
            deadline_val = m.group(1)
            deadline_q = s
            break

    funding_val = None
    funding_q = None
    funding_type = "unknown"
    for s in sentences:
        if re.search(r"\b(full|tuition|stipend|fellowship|fully funded|منحة كاملة)\b", s, re.IGNORECASE):
            funding_val = s[:220]
            funding_q = s
            funding_type = "full" if re.search(r"\b(full|fully funded|كاملة)\b", s, re.IGNORECASE) else "partial"
            break

    docs: List[str] = []
    docs_q = None
    for s in sentences:
        if re.search(r"\b(cv|resume|transcript|recommendation|motivation letter|passport|statement of purpose)\b", s, re.IGNORECASE):
            docs.append(s[:180])
            if not docs_q:
                docs_q = s

    how_to = None
    how_q = None
    for s in sentences:
        if re.search(r"\b(apply|application portal|submit online|لتقديم|بوابة التقديم)\b", s, re.IGNORECASE):
            how_to = s[:240]
            how_q = s
            break

    legacy_prof = LegacyStudentProfile(
        major=req.major,
        degree_level=req.target_degree,
        target_country=req.target_countries[0] if req.target_countries else None,
    )
    match_reason, match_quote = find_profile_match_evidence(clean_text, legacy_prof)

    raw_fields: Dict[str, Any] = {
        "title": title,
        "description": sentences[0][:300] if sentences else None,
        "eligibility": [nat_quote] if nat_quote else [],
        "criteria": [match_quote] if match_quote else [],
        "fields_of_study": [req.major] if match_quote and req.major.lower() in normalize_text(match_quote) else [],
        "funding": funding_val,
        "required_documents": docs[:5],
        "deadline": deadline_val,
        "how_to_apply": how_to,
        "accepts_yemeni": "yes" if (norm_nat == "YE" and _verdict == "yes") else ("no" if (norm_nat == "YE" and _verdict == "no") else "unclear"),
        "provider_name": None,
        "host_country": None,
        "allowed_degrees": [req.target_degree] if match_quote else [],
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": nat_rule,
        "min_work_years": None,
        "max_age": None,
        "funding_type": funding_type,
    }
    ev: Dict[str, str] = {}
    if is_quote_in_text(title, page_text):
        ev["title"] = title
    if sentences:
        ev["description"] = sentences[0]
    if nat_quote:
        ev["eligibility"] = nat_quote
        ev["nationality_rule"] = nat_quote
    if match_quote:
        ev["allowed_degrees"] = match_quote
        ev["criteria"] = match_quote
    if funding_q:
        ev["funding"] = funding_q
        ev["funding_type"] = funding_q
    if docs_q:
        ev["required_documents"] = docs_q
    if deadline_q:
        ev["deadline"] = deadline_q
    if how_q:
        ev["how_to_apply"] = how_q

    sanitized, verification = verify_evidence(fields=raw_fields, evidence=ev, page_text=page_text)
    if sanitized.get("title") is None:
        sanitized["title"] = title
    return sanitized, ev, verification


class ProfileExternalSearchService:
    """Executes profile-aware, SSRF-guarded, evidence-verified, budget-bounded external search."""

    def __init__(
        self,
        *,
        search_fn: Optional[Callable[[str, int], List[Dict[str, str]]]] = None,
        fetch_fn: Optional[Callable[[str], Tuple[str, List[Dict[str, str]]]]] = None,
        validate_fn: Optional[Callable[[str, Optional[str]], Tuple[bool, List[str]]]] = None,
    ) -> None:
        self._search_fn = search_fn or search_web
        self._fetch_fn = fetch_fn or fetch_page
        self._validate_fn = validate_fn or validate_official_url

    async def run_search(
        self,
        *,
        request: ExternalSearchRunRequest,
        llm: Optional[AsyncLLMClient] = None,
        budget: Optional[SearchRunBudget] = None,
        owner_session_id: Optional[str] = None,
    ) -> ExternalSearchRunResponse:
        run_id = (request.run_id or str(uuid.uuid4()))[:64]
        active_budget = budget or SearchRunBudget(
            max_queries=settings.SEARCH_MAX_QUERIES,
            max_pages=settings.SEARCH_MAX_PAGES,
            max_steps=settings.SEARCH_MAX_STEPS,
            wall_clock_seconds=settings.SEARCH_WALL_CLOCK_SECONDS,
            max_tokens=settings.SEARCH_MAX_TOKENS_PER_RUN,
        )
        with _ACTIVE_LOCK:
            _ACTIVE_BUDGETS[run_id] = (active_budget, owner_session_id)

        try:
            return await self._execute_run(run_id=run_id, request=request, llm=llm, budget=active_budget)
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE_BUDGETS.pop(run_id, None)

    async def _execute_run(
        self,
        *,
        run_id: str,
        request: ExternalSearchRunRequest,
        llm: Optional[AsyncLLMClient],
        budget: SearchRunBudget,
    ) -> ExternalSearchRunResponse:
        prof_dict = self._build_student_profile_dict(request)
        platform_entries, platform_fingerprint = (
            _load_platform_grants_index() if request.exclude_platform_grants else ([], "none")
        )
        cache_payload: Dict[str, Any] = {
            "nationality": prof_dict["nationality"],
            "target_degree": prof_dict["target_degree"],
            "major": prof_dict["major"].lower(),
            "target_countries": sorted(prof_dict["target_countries"]),
            "target_fields": sorted(prof_dict["target_fields"]),
            "gpa_normalized_4": prof_dict.get("gpa_normalized_4"),
        }
        if (
            prof_dict.get("languages")
            or request.exclude_platform_grants
            or request.only_eligible
            or request.max_results is not None
        ):
            cache_payload["languages"] = sorted(
                f"{l.get('language', '')}:{l.get('test_name', '')}:{l.get('score', '')}:{l.get('self_assessed_cefr', '')}"
                for l in prof_dict.get("languages", [])
            )
            cache_payload["exclude_platform_grants"] = request.exclude_platform_grants
            cache_payload["only_eligible"] = request.only_eligible
            cache_payload["max_results"] = request.max_results
            cache_payload["platform_fp"] = platform_fingerprint
        cache_key = make_profile_cache_key(cache_payload)
        if request.use_cache:
            with get_db() as db:
                hit = SearchCacheRepository.get_cached(db, cache_key)
            if hit:
                hit["run_id"] = run_id
                hit["cached"] = True
                return ExternalSearchRunResponse(**hit)

        step_log: List[ExternalSearchStepLog] = []
        results: List[ExternalSearchCandidateResult] = []
        seen_urls: Set[str] = set()
        excluded_platform_count = 0

        # 1. Plan search queries (1 bounded LLM call if configured, else deterministic)
        queries = await self._plan_queries(request=request, llm=llm, budget=budget, step_log=step_log)

        # 2. Execute up to max_queries searches
        candidates: List[Dict[str, str]] = []
        per_query_hits = 8 if request.exclude_platform_grants else 6
        for q in queries[: budget.max_queries]:
            if stop := budget.stop_reason():
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken + 1,
                        kind="budget_stop",
                        verdict="stopped",
                        message_ar=stop[0],
                        message_en=stop[1],
                    )
                )
                return self._finish(
                    run_id,
                    "partial",
                    stop[0],
                    stop[1],
                    budget,
                    step_log,
                    results,
                    cache_key,
                    save_cache=False,
                    excluded_platform_count=excluded_platform_count,
                    max_results=request.max_results,
                )

            budget.steps_taken += 1
            budget.queries_used += 1
            try:
                found = await asyncio.to_thread(self._search_fn, q, per_query_hits)
                for item in found:
                    u = str(item.get("url") or "").strip()
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        candidates.append(item)
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="search",
                        target=q,
                        verdict="ok",
                        message_ar=f"استعلام البحث أعاد {len(found)} روابط مرشحة.",
                        message_en=f"Search query returned {len(found)} candidate URLs.",
                    )
                )
            except Exception as exc:
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="search",
                        target=q,
                        verdict="rejected",
                        message_ar=f"تعذّر تنفيذ البحث ({type(exc).__name__}).",
                        message_en=f"Search provider error ({type(exc).__name__}).",
                    )
                )
                if not candidates and budget.queries_used >= len(queries):
                    return self._finish(
                        run_id,
                        "failed",
                        "تعذّر الاتصال بمحرك البحث الخارجي.",
                        "External search provider failed.",
                        budget,
                        step_log,
                        results,
                        cache_key,
                        save_cache=False,
                        excluded_platform_count=excluded_platform_count,
                        max_results=request.max_results,
                    )

        if not candidates:
            return self._finish(
                run_id,
                "complete",
                "لم يُعثر على نتائج مطابقة للملف في المواقع الموثوقة.",
                "No candidate grants returned for this profile.",
                budget,
                step_log,
                results,
                cache_key,
                save_cache=True,
                excluded_platform_count=excluded_platform_count,
                max_results=request.max_results,
            )

        # 3. Validate, deduplicate against ASAAS grants, fetch safely (SSRF guard), extract & score
        fetched_urls: Set[str] = set()
        for cand in candidates:
            if request.only_eligible and request.max_results and len(results) >= request.max_results + 2:
                break
            if stop := budget.stop_reason():
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken + 1,
                        kind="budget_stop",
                        verdict="stopped",
                        message_ar=stop[0],
                        message_en=stop[1],
                    )
                )
                return self._finish(
                    run_id,
                    "partial",
                    stop[0],
                    stop[1],
                    budget,
                    step_log,
                    results,
                    cache_key,
                    save_cache=False,
                    excluded_platform_count=excluded_platform_count,
                    max_results=request.max_results,
                )

            url = str(cand.get("url") or "").strip()
            title = str(cand.get("title") or "Scholarship").strip()
            if not url or url in fetched_urls:
                continue
            fetched_urls.add(url)

            if request.exclude_platform_grants and _matches_platform_grant(url, title, platform_entries):
                excluded_platform_count += 1
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="validate_url",
                        target=url,
                        verdict="skipped",
                        message_ar=f"تم تخطي '{title}' لأنها موجودة بالفعل ضمن منح أساس.",
                        message_en=f"Skipped '{title}' because it already exists in ASAAS platform grants.",
                    )
                )
                continue

            # Domain + outbound guard validation
            is_valid, reasons = await asyncio.to_thread(self._validate_fn, url, title)
            if not is_valid:
                budget.steps_taken += 1
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="validate_url",
                        target=url,
                        verdict="rejected",
                        message_ar=f"مرفوض: {reasons[0] if reasons else 'نطاق غير رسمي أو مجمع روابط'}",
                        message_en=f"Rejected: {'; '.join(reasons)}",
                    )
                )
                continue

            # Fetch page safely through Phase 1 outbound URL guard
            budget.steps_taken += 1
            budget.pages_fetched += 1
            try:
                page_text, _ = await asyncio.to_thread(self._fetch_fn, url)
            except UnsafeURLError as exc:
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="fetch_page",
                        target=url,
                        verdict="rejected",
                        message_ar=f"محجوب أمنياً (SSRF/رابط غير آمن): {exc}",
                        message_en=f"Blocked by outbound URL guard: {exc}",
                    )
                )
                continue
            except Exception as exc:
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="fetch_page",
                        target=url,
                        verdict="rejected",
                        message_ar=f"تعذّر فتح الصفحة ({type(exc).__name__}).",
                        message_en=f"Failed to fetch page ({type(exc).__name__}).",
                    )
                )
                continue

            if not page_text or not page_text.strip():
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="fetch_page",
                        target=url,
                        verdict="rejected",
                        message_ar="الصفحة فارغة ولا تحتوي نصاً قابلاً للتحقق.",
                        message_en="Fetched page is empty.",
                    )
                )
                continue

            c_hash = compute_content_hash(page_text)
            sanitized, evidence, verification = await self._extract_and_verify(
                url=url,
                title=title,
                page_text=page_text,
                c_hash=c_hash,
                request=request,
                llm=llm,
                budget=budget,
                step_log=step_log,
            )

            extracted_title = str(sanitized.get("title") or title)
            if request.exclude_platform_grants and _matches_platform_grant(url, extracted_title, platform_entries):
                excluded_platform_count += 1
                step_log.append(
                    ExternalSearchStepLog(
                        step_number=budget.steps_taken,
                        kind="validate_url",
                        target=url,
                        verdict="skipped",
                        message_ar=f"تم تخطي '{extracted_title}' لتطابقها مع منحة منشورة في أساس.",
                        message_en=f"Skipped '{extracted_title}' because it matches an existing ASAAS grant.",
                    )
                )
                continue

            # Evaluate with identical Phase 3 matcher
            grant_for_match = dict(sanitized)
            grant_for_match["id"] = len(results) + 1
            grant_for_match["official_url"] = url
            grant_for_match["status"] = "published"
            grant_for_match["evidence"] = evidence
            match_res = evaluate_grant_for_student(grant_for_match, prof_dict)

            if request.only_eligible:
                field_crit = next((c for c in match_res.criteria if c.key == "field_of_study"), None)
                if (
                    not match_res.eligible
                    or match_res.match_percentage <= 0
                    or (field_crit is not None and field_crit.status == "not_met")
                ):
                    step_log.append(
                        ExternalSearchStepLog(
                            step_number=budget.steps_taken,
                            kind="extract",
                            target=url,
                            verdict="skipped",
                            message_ar=f"استُبعدت '{extracted_title}' لعدم توافقها مع شروط ملفك ({match_res.match_percentage}%).",
                            message_en=f"Filtered out '{extracted_title}' (eligible={match_res.eligible}, match={match_res.match_percentage}%).",
                        )
                    )
                    continue

            nat_rule = sanitized.get("nationality_rule") or {"mode": "unclear", "countries": [], "groups": []}
            nat_verdict = evaluate_nationality(prof_dict["nationality"], nat_rule)
            nat_ev = evidence.get("nationality_rule") or evidence.get("eligibility") or evidence.get("accepts_yemeni")

            results.append(
                ExternalSearchCandidateResult(
                    title=extracted_title,
                    official_url=url,
                    content_hash=c_hash,
                    description=sanitized.get("description"),
                    eligibility=list(sanitized.get("eligibility") or []),
                    criteria=list(sanitized.get("criteria") or []),
                    fields_of_study=list(sanitized.get("fields_of_study") or []),
                    funding=sanitized.get("funding"),
                    funding_type=str(sanitized.get("funding_type") or "unknown"),
                    required_documents=list(sanitized.get("required_documents") or []),
                    deadline=sanitized.get("deadline"),
                    how_to_apply=sanitized.get("how_to_apply"),
                    provider_name=sanitized.get("provider_name"),
                    host_country=sanitized.get("host_country"),
                    allowed_degrees=list(sanitized.get("allowed_degrees") or []),
                    nationality_rule=nat_rule,
                    eligibility_verdict=nat_verdict,
                    nationality_evidence=nat_ev,
                    evidence=evidence,
                    field_verification=verification,
                    match_result=match_res,
                )
            )
            step_log.append(
                ExternalSearchStepLog(
                    step_number=budget.steps_taken,
                    kind="extract",
                    target=url,
                    verdict="ok",
                    message_ar=f"تم التحقق من {extracted_title} (تطابق {match_res.match_percentage}%).",
                    message_en=f"Verified {extracted_title} (match {match_res.match_percentage}%).",
                )
            )

        # Rank verified results cleanly (eligible & highest Phase 3 match + coverage first)
        results.sort(
            key=lambda r: (
                0 if r.match_result.eligible else 1,
                -r.match_result.match_percentage,
                -r.match_result.coverage_percentage,
            )
        )
        return self._finish(
            run_id,
            "complete",
            f"اكتمل البحث وفحص {budget.pages_fetched} صفحة رسمية.",
            f"Completed search across {budget.pages_fetched} checked pages.",
            budget,
            step_log,
            results,
            cache_key,
            save_cache=True,
            excluded_platform_count=excluded_platform_count,
            max_results=request.max_results,
        )

    def _build_student_profile_dict(self, req: ExternalSearchRunRequest) -> Dict[str, Any]:
        gpa_4 = None
        if req.gpa_raw and req.gpa_scale:
            try:
                gpa_4, _ = normalize_student_gpa(req.gpa_raw, req.gpa_scale)
            except ValueError:
                gpa_4 = None
        return {
            "nationality": req.nationality,
            "target_degree": req.target_degree,
            "major": req.major,
            "target_countries": [c.upper() if len(c) == 2 else c for c in req.target_countries],
            "target_fields": req.target_fields or [req.major],
            "gpa_raw": req.gpa_raw,
            "gpa_scale": req.gpa_scale,
            "gpa_normalized_4": gpa_4,
            "languages": [l.model_dump() for l in req.languages],
        }

    async def _plan_queries(
        self,
        *,
        request: ExternalSearchRunRequest,
        llm: Optional[AsyncLLMClient],
        budget: SearchRunBudget,
        step_log: List[ExternalSearchStepLog],
    ) -> List[str]:
        fallback = _deterministic_queries(request)
        if llm is None or not getattr(llm, "_configured", False) or budget.tokens_used + 350 > budget.max_tokens:
            return fallback

        system_prompt, prompt_version = load_prompt("search_planner")
        profile_summary = {
            "nationality": request.nationality,
            "target_degree": request.target_degree,
            "major": request.major,
            "target_countries": request.target_countries,
            "target_fields": request.target_fields,
            "languages": [l.model_dump(exclude_none=True) for l in request.languages],
        }
        try:
            budget.tokens_used += 350
            plan = await llm.structured(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(profile_summary, ensure_ascii=False)},
                ],
                SearchQueryPlanLLM,
                prompt_version=prompt_version,
                max_tokens=300,
                temperature=0.1,
            )
            step_log.append(
                ExternalSearchStepLog(
                    step_number=budget.steps_taken,
                    kind="plan_queries",
                    verdict="ok",
                    message_ar=f"تم توليد {len(plan.queries[:budget.max_queries])} استعلامات بحث من ملف الطالب.",
                    message_en=f"Generated {len(plan.queries[:budget.max_queries])} queries from full profile.",
                )
            )
            return plan.queries[: budget.max_queries]
        except LLMError:
            return fallback

    async def _extract_and_verify(
        self,
        *,
        url: str,
        title: str,
        page_text: str,
        c_hash: str,
        request: ExternalSearchRunRequest,
        llm: Optional[AsyncLLMClient],
        budget: SearchRunBudget,
        step_log: List[ExternalSearchStepLog],
    ) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, str]]:
        p_cache_key = make_page_cache_key(url, c_hash)
        with get_db() as db:
            page_hit = SearchCacheRepository.get_cached(db, p_cache_key)
        if page_hit:
            step_log.append(
                ExternalSearchStepLog(
                    step_number=budget.steps_taken,
                    kind="cache_hit",
                    target=url,
                    verdict="ok",
                    message_ar=f"تم استرجاع التحليل الموثق من الذاكرة المؤقتة لـ {title}.",
                    message_en=f"Loaded verified extraction from cache for {title}.",
                )
            )
            return (
                dict(page_hit["sanitized"]),
                dict(page_hit["evidence"]),
                dict(page_hit["verification"]),
            )

        if llm is not None and getattr(llm, "_configured", False) and budget.tokens_used + 1000 <= budget.max_tokens:
            try:
                budget.tokens_used += 1000
                ext: GrantExtractionSchema = await extract_grant_from_text_async(page_text, llm)
                raw_fields = {
                    "title": ext.title or title,
                    "description": ext.description,
                    "eligibility": ext.eligibility,
                    "criteria": ext.criteria,
                    "fields_of_study": ext.fields_of_study,
                    "funding": ext.funding,
                    "required_documents": ext.required_documents,
                    "deadline": ext.deadline,
                    "how_to_apply": ext.how_to_apply,
                    "accepts_yemeni": ext.accepts_yemeni,
                    "provider_name": ext.provider_name,
                    "host_country": ext.host_country,
                    "allowed_degrees": ext.allowed_degrees,
                    "min_gpa_value": ext.min_gpa_value,
                    "min_gpa_scale": ext.min_gpa_scale,
                    "language_requirements": (
                        [i.model_dump() for i in ext.language_requirements]
                        if ext.language_requirements
                        else None
                    ),
                    "nationality_rule": ext.nationality_rule.model_dump(),
                    "min_work_years": ext.min_work_years,
                    "max_age": ext.max_age,
                    "funding_type": ext.funding_type,
                }
                sanitized, verification = verify_evidence(
                    fields=raw_fields,
                    evidence=ext.evidence,
                    page_text=page_text,
                )
                if not sanitized.get("title"):
                    sanitized["title"] = title
                with get_db() as db:
                    SearchCacheRepository.set_cached(
                        db,
                        p_cache_key,
                        {"sanitized": sanitized, "evidence": ext.evidence, "verification": verification},
                        ttl_hours=settings.SEARCH_CACHE_TTL_HOURS,
                    )
                return sanitized, ext.evidence, verification
            except LLMError:
                pass

        sanitized, evidence, verification = _deterministic_extract_verified(
            url=url, title=title, page_text=page_text, req=request
        )
        with get_db() as db:
            SearchCacheRepository.set_cached(
                db,
                p_cache_key,
                {"sanitized": sanitized, "evidence": evidence, "verification": verification},
                ttl_hours=settings.SEARCH_CACHE_TTL_HOURS,
            )
        return sanitized, evidence, verification

    def _finish(
        self,
        run_id: str,
        status: Any,
        reason_ar: str,
        reason_en: str,
        budget: SearchRunBudget,
        step_log: List[ExternalSearchStepLog],
        results: List[ExternalSearchCandidateResult],
        cache_key: str,
        *,
        save_cache: bool,
        excluded_platform_count: int = 0,
        max_results: Optional[int] = None,
    ) -> ExternalSearchRunResponse:
        final_results = results[:max_results] if max_results else results
        resp = ExternalSearchRunResponse(
            run_id=run_id,
            status=status,
            stop_reason_ar=reason_ar,
            stop_reason_en=reason_en,
            cached=False,
            queries_executed=budget.queries_used,
            pages_checked=budget.pages_fetched,
            steps_taken=budget.steps_taken,
            tokens_used=budget.tokens_used,
            elapsed_ms=budget.elapsed_ms(),
            excluded_platform_count=excluded_platform_count,
            step_log=step_log,
            results=final_results,
        )
        if save_cache and status == "complete" and final_results:
            with get_db() as db:
                SearchCacheRepository.set_cached(
                    db,
                    cache_key,
                    resp.model_dump(),
                    ttl_hours=settings.SEARCH_CACHE_TTL_HOURS,
                )
        return resp

    def promote_to_draft(self, payload: PromoteExternalGrantRequest) -> Dict[str, Any]:
        """Promote a verified external scholarship into a DRAFT grant for admin review (never published automatically)."""
        is_ok, reasons = self._validate_fn(payload.official_url, payload.title)
        if not is_ok:
            raise UnsafeURLError("; ".join(reasons) or "Blocked untrusted or unsafe URL.")
        dl_date = None
        if payload.deadline:
            try:
                dl_date = date.fromisoformat(payload.deadline[:10])
            except ValueError:
                dl_date = None
        data = {
            "title": payload.title,
            "official_url": payload.official_url,
            "description": payload.description,
            "eligibility": payload.eligibility,
            "criteria": payload.criteria,
            "fields_of_study": payload.fields_of_study,
            "funding": payload.funding,
            "required_documents": payload.required_documents,
            "deadline": dl_date,
            "how_to_apply": payload.how_to_apply,
            "provider_name": payload.provider_name,
            "host_country": payload.host_country,
            "allowed_degrees": payload.allowed_degrees,
            "funding_type": payload.funding_type or "unknown",
            "nationality_rule": payload.nationality_rule or {"mode": "unclear", "countries": [], "groups": []},
            "evidence": payload.evidence or {},
            "content_hash": payload.content_hash,
            "status": GrantStatus.DRAFT,
        }
        with get_db() as db:
            grant = save_draft(db, data)
            return grant.to_dict()
