"""Runs one feature's evaluation set and compares it with the saved baseline.

Usage:
    python -m evals.run_eval extraction            # run and compare (auto-uses live LLM if LLM_API_KEY is set, else stub)
    python -m evals.run_eval extraction --save     # save baseline ONLY when run against a real model (LLM_API_KEY present)
    python -m evals.run_eval extraction --stub     # force stub mode (never saves baseline)
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

from core.config import settings
from evals.features import eval_advisor, eval_documents, eval_external_search, eval_extraction, eval_profile_analysis

EVALS_DIR = Path(__file__).resolve().parent

FEATURES: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {
    "extraction": eval_extraction,
    "profile_analysis": eval_profile_analysis,
    "advisor": eval_advisor,
    "documents": eval_documents,
    "external_search": eval_external_search,
}


def _resolve_field(output: Dict[str, Any], dotted_key: str) -> Any:
    current: Any = output
    for part in dotted_key.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def check(expect: Dict[str, Any], output: Dict[str, Any]) -> List[str]:
    """Deterministic checks including evidence verification."""
    failures: List[str] = []

    for key, wanted in expect.get("equals", {}).items():
        actual = _resolve_field(output, key)
        if actual != wanted:
            failures.append(f"{key}: expected {wanted!r}, got {actual!r}")

    text = json.dumps(output, ensure_ascii=False).lower()
    for phrase in expect.get("contains", []):
        if phrase.lower() not in text:
            failures.append(f"missing {phrase!r}")
    for phrase in expect.get("not_contains", []):
        if phrase.lower() in text:
            failures.append(f"must not contain {phrase!r}")

    for req_field in expect.get("verified_fields", []):
        verdict = (output.get("field_verification") or {}).get(req_field)
        if verdict != "verified":
            failures.append(f"evidence_check failed for {req_field!r}: {verdict!r}")

    # Anti-hallucination invariant: any unverified field that had to be stripped
    # fails only if explicitly required in verified_fields or unverified_disallow.
    for req_field in expect.get("no_unverified", []):
        verdict = (output.get("field_verification") or {}).get(req_field)
        if verdict == "unverified":
            failures.append(f"field {req_field!r} returned unverified hallucinated value")

    if expect.get("arabic_output"):
        summary = str(output.get("summary_ar") or output.get("reply") or "")
        if not re.search(r"[\u0600-\u06ff]", summary):
            failures.append("arabic output contains no Arabic text")

    if "tools_used_any" in expect:
        used = set(output.get("tools_used") or [])
        wanted_tools = expect.get("tools_used_any") or []
        if not any(t in used for t in wanted_tools):
            failures.append(f"expected one of tools {wanted_tools!r}, got {sorted(used)!r}")

    if "tools_not_used" in expect:
        used = set(output.get("tools_used") or [])
        forbidden = [t for t in (expect.get("tools_not_used") or []) if t in used]
        if forbidden:
            failures.append(f"forbidden tools used: {forbidden!r}")

    if "has_proposal" in expect:
        if bool(output.get("has_proposal")) != bool(expect["has_proposal"]):
            failures.append(
                f"has_proposal: expected {expect['has_proposal']!r}, got {output.get('has_proposal')!r}"
            )

    if expect.get("profile_unchanged") and output.get("profile_changed_in_db"):
        failures.append("student profile mutated directly in DB by assistant")

    if expect.get("no_fabricated_percentages"):
        reply_text = str(output.get("reply") or "")
        tool_blob = json.dumps(output.get("tool_outputs") or [], ensure_ascii=False)
        for pct in re.findall(r"\b(\d+(?:\.\d+)?)\s*%", reply_text):
            if pct not in tool_blob and pct != "100":
                failures.append(f"fabricated percentage {pct}% not found in tool outputs")

    # Document draft & Facts Ledger deterministic checks (Phase 5)
    if "has_conflict" in expect:
        if bool(output.get("has_conflict")) != bool(expect["has_conflict"]):
            failures.append(
                f"has_conflict: expected {expect['has_conflict']!r}, got {output.get('has_conflict')!r}"
            )

    if "has_missing_request" in expect:
        if bool(output.get("has_missing_request")) != bool(expect["has_missing_request"]):
            failures.append(
                f"has_missing_request: expected {expect['has_missing_request']!r}, got {output.get('has_missing_request')!r}"
            )

    if expect.get("no_recommender_voice"):
        flagged = output.get("flagged_claims") or []
        if any(c.get("category") == "recommendation_voice" for c in flagged):
            failures.append("draft slipped into recommender first-person voice")

    for tok in expect.get("no_unflagged_tokens", []):
        draft_low = str(output.get("draft_text") or "").lower()
        if tok.lower() in draft_low:
            flagged_blob = " ".join(str(c.get("claim_text") or "").lower() for c in (output.get("flagged_claims") or []))
            if tok.lower() not in flagged_blob:
                failures.append(f"fabricated token {tok!r} appeared in draft without being flagged")

    for tok in expect.get("not_contains_in_clean_draft", []):
        draft_low = str(output.get("draft_text") or "").lower()
        if tok.lower() in draft_low:
            failures.append(f"fabricated phrase {tok!r} must not be in draft_text")

    if expect.get("all_statements_referenced"):
        valid_ids = {f.get("id") for f in (output.get("findings") or []) if f.get("id")}
        for section in ("strengths", "weaknesses", "improvement_areas"):
            for item in output.get(section) or []:
                fids = item.get("finding_ids") or []
                if not fids or any(fid not in valid_ids for fid in fids):
                    failures.append(f"ungrounded statement in {section}: {fids!r}")

    if expect.get("no_pii_in_llm_input"):
        captured_str = json.dumps(output.get("_captured_llm_input") or [], ensure_ascii=False)
        for marker in output.get("_raw_student_pii_markers") or []:
            if str(marker) in captured_str:
                failures.append(f"PII marker leaked to LLM input: {marker!r}")
        if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", captured_str):
            failures.append("email leaked into LLM input")
        if "session_id" in captured_str:
            failures.append("session_id key appeared in LLM input")

        # Verify no invented standalone numbers inside model narrative text outside allowed input numbers
        narrative_chunks = [str(output.get("summary_ar") or "")]
        for section in ("strengths", "weaknesses", "improvement_areas"):
            for item in output.get(section) or []:
                narrative_chunks.append(str(item.get("text_ar") or ""))
        allowed_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", captured_str))
        allowed_nums |= {"10", "100"}
        for num in re.findall(r"\b\d+(?:\.\d+)?\b", " ".join(narrative_chunks)):
            if num not in allowed_nums:
                failures.append(f"invented number {num!r} in narrative")

    return failures


async def run(feature: str, *, live: bool) -> Dict[str, Any]:
    cases_path = EVALS_DIR / feature / "cases.jsonl"
    cases = [
        json.loads(line)
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results: Dict[str, Any] = {}
    for case in cases:
        started = time.perf_counter()
        try:
            output = await FEATURES[feature](case["input"], live=live)
            failures = check(case.get("expect", {}), output)
        except Exception as error:
            output, failures = {}, [f"error: {type(error).__name__}: {error}"]
        results[case["id"]] = {
            "passed": not failures,
            "failures": failures,
            "ms": round((time.perf_counter() - started) * 1000),
        }
    return results


def compare(feature: str, results: Dict[str, Any], save: bool, live: bool) -> int:
    baseline_path = EVALS_DIR / feature / "baseline.json"
    baseline = (
        json.loads(baseline_path.read_text(encoding="utf-8"))
        if baseline_path.exists()
        else {}
    )
    passed = sum(1 for r in results.values() if r["passed"])
    mode_label = "LIVE MODEL" if live else "STUB CLIENT (no LLM_API_KEY)"
    print(f"{feature} [{mode_label}]: {passed}/{len(results)} passed")

    regressions = [
        cid
        for cid, r in results.items()
        if not r["passed"] and baseline.get(cid, {}).get("passed")
    ]
    fixed = [
        cid
        for cid, r in results.items()
        if r["passed"] and cid in baseline and not baseline[cid].get("passed")
    ]
    for cid, r in results.items():
        if not r["passed"]:
            print(f"  FAIL {cid}: {'; '.join(r['failures'])}")
    if fixed:
        print(f"  fixed since baseline: {', '.join(fixed)}")
    if regressions:
        print(f"  REGRESSED since baseline: {', '.join(regressions)}")

    if save:
        if not live:
            print("  NOTE: --save ignored because runner executed with stub client (no LLM_API_KEY).")
        else:
            baseline_path.write_text(
                json.dumps(results, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"  baseline saved to {baseline_path}")

    return 1 if regressions else 0


def main(argv: List[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] not in FEATURES:
        print(f"Usage: python -m evals.run_eval <{'|'.join(FEATURES)}> [--save] [--stub]")
        return 2
    feature = args[0]
    force_stub = "--stub" in args
    want_save = "--save" in args
    has_key = bool((os.getenv("LLM_API_KEY") or settings.LLM_API_KEY or "").strip())
    live = has_key and not force_stub
    results = asyncio.run(run(feature, live=live))
    return compare(feature, results, save=want_save, live=live)


if __name__ == "__main__":
    raise SystemExit(main())
