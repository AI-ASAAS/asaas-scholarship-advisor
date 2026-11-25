"""Deterministic structured backfill for the 10 verified baseline scholarships.

Built strictly from the recorded facts and verbatim quotes already present in
`seed/seed_db.py` (`VERIFIED_TOP10_BASELINE`). Never adds ungrounded data from memory.
Every non-null structured field is gated through `utils.evidence_check.is_quote_in_text`
against the saved recorded fixture text for that grant.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from modules.matching.gpa import normalize_gpa_to_4
from modules.matching.nationalities import evaluate_nationality
from utils.evidence_check import is_quote_in_text

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _render_grant_text(entry: Dict[str, Any]) -> str:
    """Render a deterministic plain-text fixture snapshot from a recorded baseline entry."""
    lines: List[str] = [
        f"Title: {entry.get('title', '')}",
        f"Official URL: {entry.get('official_url', '')}",
    ]
    if entry.get("description"):
        lines.append(f"Overview: {entry['description']}")
    if entry.get("eligibility"):
        lines.append("Eligibility Requirements:")
        for item in entry["eligibility"]:
            lines.append(f"- {item}")
    if entry.get("criteria"):
        lines.append("Selection Criteria:")
        for item in entry["criteria"]:
            lines.append(f"- {item}")
    if entry.get("fields_of_study"):
        lines.append("Fields of Study: " + ", ".join(entry["fields_of_study"]))
    if entry.get("funding"):
        lines.append(f"Funding: {entry['funding']}")
    if entry.get("required_documents"):
        lines.append("Required Documents: " + ", ".join(entry["required_documents"]))
    deadline_quote = (entry.get("evidence") or {}).get("deadline")
    if entry.get("deadline") or deadline_quote:
        lines.append(f"Deadline: {deadline_quote or ''} ({entry.get('deadline')})")
    if entry.get("how_to_apply"):
        lines.append(f"How to Apply: {entry['how_to_apply']}")
    return "\n".join(lines)


# Candidates derived ONLY from text inside VERIFIED_TOP10_BASELINE (unchanged facts).
# Any field omitted/None stays unknown (None). Each non-null field carries an exact quote
# checked programmatically against the recorded text before backfill.
_RECORDED_STRUCTURED_CANDIDATES: Dict[str, Dict[str, Any]] = {
    "https://www.turkiyeburslari.gov.tr/": {
        "provider_name": "Türkiye Bursları",
        "host_country": "TR",
        "allowed_degrees": ["bachelor", "master", "phd"],
        "min_gpa_value": 70.0,
        "min_gpa_scale": "100",
        "language_requirements": None,
        "nationality_rule": {
            "mode": "all",
            "countries": [],
            "groups": [],
            "evidence": "Citizens of all countries including Yemen are eligible to apply.",
        },
        "min_work_years": None,
        "max_age": 35,
        "funding_type": "full",
        "quotes": {
            "provider_name": "Türkiye Bursları (Turkish Government Scholarship)",
            "host_country": "Turkish universities",
            "allowed_degrees": "undergraduate, master's, and doctoral studies",
            "min_gpa": "Minimum academic achievement of 70% for bachelor's, 75% for master's and PhD",
            "nationality_rule": "Citizens of all countries including Yemen are eligible to apply.",
            "max_age": "Under 21 years of age for undergraduate, under 30 for master's, under 35 for PhD.",
            "funding_type": "Full university tuition, monthly stipend, free student dormitory accommodation",
        },
    },
    "https://www.chevening.org/scholarships/": {
        "provider_name": "UK government",
        "host_country": "GB",
        "allowed_degrees": ["master"],
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": {
            "mode": "group",
            "countries": ["YE"],
            "groups": ["chevening_eligible"],
            "evidence": "Be a citizen of a Chevening-eligible country including Yemen.",
        },
        "min_work_years": 2.0,
        "max_age": None,
        "funding_type": "full",
        "quotes": {
            "provider_name": "The UK government's global scholarship programme",
            "host_country": "at any UK university",
            "allowed_degrees": "offering full financial support for one-year master's degrees",
            "nationality_rule": "Be a citizen of a Chevening-eligible country including Yemen.",
            "min_work_years": "Have at least two years (equivalent to 2,800 hours) of work experience.",
            "funding_type": "Full university tuition fees, monthly living allowance",
        },
    },
    "https://www.daad.de/en/study-and-research-in-germany/scholarships/": {
        "provider_name": "DAAD",
        "host_country": "DE",
        "allowed_degrees": ["master"],
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": {
            "mode": "group",
            "countries": ["YE"],
            "groups": ["developing_countries"],
            "evidence": "Graduates from developing countries including Yemen.",
        },
        "min_work_years": None,
        "max_age": None,
        "funding_type": "full",
        "quotes": {
            "provider_name": "DAAD Helmut-Schmidt-Programme",
            "host_country": "German master's programmes",
            "allowed_degrees": "participating German master's programmes",
            "nationality_rule": "Graduates from developing countries including Yemen.",
            "funding_type": "Monthly scholarship payment of €934, health insurance contribution, travel subsidy",
        },
    },
    "https://stipendiumhungaricum.hu/": {
        "provider_name": "Hungarian state",
        "host_country": "HU",
        "allowed_degrees": None,
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": {
            "mode": "group",
            "countries": ["YE"],
            "groups": ["stipendium_hungaricum_partners"],
            "evidence": "Citizens of eligible sending partners including Yemen.",
        },
        "min_work_years": None,
        "max_age": None,
        "funding_type": "full",
        "quotes": {
            "provider_name": "Hungarian state scholarship programme",
            "host_country": "leading Hungarian universities",
            "nationality_rule": "Citizens of eligible sending partners including Yemen.",
            "funding_type": "Full tuition fee exemption, monthly stipend",
        },
    },
    "https://www.mae.ro/en/node/10250": {
        "provider_name": "Ministry of Foreign Affairs Romania",
        "host_country": "RO",
        "allowed_degrees": None,
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": {
            "mode": "exclude",
            "countries": [],
            "groups": ["eu"],
            "evidence": "Non-EU foreign citizens from all countries including Yemen.",
        },
        "min_work_years": None,
        "max_age": None,
        "funding_type": "full",
        "quotes": {
            "provider_name": "awarded by the Romanian state through the Ministry of Foreign Affairs",
            "host_country": "Study in Romania online platform",
            "nationality_rule": "Non-EU foreign citizens from all countries including Yemen.",
            "funding_type": "Free tuition, preparatory Romanian language year, free dormitory accommodation, and monthly financial support.",
        },
    },
    "https://foreign.fulbrightonline.org/": {
        "provider_name": "U.S. government",
        "host_country": "US",
        "allowed_degrees": ["master"],
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": [
            {"language": "English", "test": "TOEFL", "min_score": None, "cefr": None}
        ],
        "nationality_rule": {
            "mode": "include",
            "countries": ["YE"],
            "groups": [],
            "evidence": "Yemeni citizens residing in Yemen or eligible international locations.",
        },
        "min_work_years": None,
        "max_age": None,
        "funding_type": "full",
        "quotes": {
            "provider_name": "sponsored by the U.S. government",
            "host_country": "master's studies in the USA",
            "allowed_degrees": "for master's studies in the USA",
            "language_requirements": "Fluency in English (TOEFL or equivalent).",
            "nationality_rule": "Yemeni citizens residing in Yemen or eligible international locations.",
            "funding_type": "Full tuition fees, monthly living stipend, health benefit plan",
        },
    },
    "https://www.campuschina.org/": {
        "provider_name": "Ministry of Education of China",
        "host_country": "CN",
        "allowed_degrees": ["bachelor", "master", "phd"],
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": {
            "mode": "group",
            "countries": ["YE"],
            "groups": ["belt_and_road"],
            "evidence": "Citizens of Belt and Road countries including Yemen.",
        },
        "min_work_years": None,
        "max_age": 40,
        "funding_type": "full",
        "quotes": {
            "provider_name": "established by the Ministry of Education of China",
            "host_country": "chosen Chinese universities",
            "allowed_degrees": "Bachelor applicants under 25, master's under 35, doctoral under 40.",
            "nationality_rule": "Citizens of Belt and Road countries including Yemen.",
            "max_age": "Bachelor applicants under 25, master's under 35, doctoral under 40.",
            "funding_type": "Tuition waiver, free on-campus university accommodation, comprehensive medical insurance, and monthly living stipend",
        },
    },
    "https://education-in-russia.com/": {
        "provider_name": "Russian Federation",
        "host_country": "RU",
        "allowed_degrees": None,
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": {
            "mode": "include",
            "countries": ["YE"],
            "groups": [],
            "evidence": "Foreign citizens from designated quota countries including Yemen.",
        },
        "min_work_years": None,
        "max_age": None,
        "funding_type": "full",
        "quotes": {
            "provider_name": "funded by the Russian Federation",
            "host_country": "Education in Russia official portal",
            "nationality_rule": "Foreign citizens from designated quota countries including Yemen.",
            "funding_type": "100% tuition coverage for the entire degree duration",
        },
    },
    "https://www.isdb.org/scholarships": {
        "provider_name": "Islamic Development Bank (IsDB)",
        "host_country": None,
        "allowed_degrees": None,
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": [
            {"language": "English", "test": None, "min_score": None, "cefr": None},
            {"language": "French", "test": None, "min_score": None, "cefr": None},
        ],
        "nationality_rule": {
            "mode": "group",
            "countries": ["YE"],
            "groups": ["isdb_members"],
            "evidence": "Citizens of IsDB member countries including Yemen.",
        },
        "min_work_years": None,
        "max_age": None,
        "funding_type": "full",
        "quotes": {
            "provider_name": "Islamic Development Bank (IsDB) Scholarship Programme",
            "language_requirements": "English/French language proficiency proof",
            "nationality_rule": "Citizens of IsDB member countries including Yemen.",
            "funding_type": "Full university tuition, monthly living allowance commensurate with cost of living",
        },
    },
    "https://www.campusfrance.org/en/the-eiffel-scholarship-program-of-excellence": {
        "provider_name": "French Ministry for Europe and Foreign Affairs",
        "host_country": "FR",
        "allowed_degrees": ["master", "phd"],
        "min_gpa_value": None,
        "min_gpa_scale": None,
        "language_requirements": None,
        "nationality_rule": {
            "mode": "group",
            "countries": ["YE"],
            "groups": ["developing_countries"],
            "evidence": "Non-French foreign citizens from developing countries including Yemen.",
        },
        "min_work_years": None,
        "max_age": 32,
        "funding_type": "full",
        "quotes": {
            "provider_name": "French Ministry for Europe and Foreign Affairs scholarship",
            "host_country": "French higher education institutions",
            "allowed_degrees": "Up to 27 years of age for master's level, up to 32 for PhD level.",
            "nationality_rule": "Non-French foreign citizens from developing countries including Yemen.",
            "max_age": "Up to 27 years of age for master's level, up to 32 for PhD level.",
            "funding_type": "Monthly allowance of €1,181 for master's (€1,800 for PhD), international round-trip airfare",
        },
    },
}


def build_verified_backfill_map() -> Dict[str, Dict[str, Any]]:
    """Verify every backfill candidate against the recorded baseline grant text."""
    from seed.seed_db import VERIFIED_TOP10_BASELINE

    by_url = {entry["official_url"]: entry for entry in VERIFIED_TOP10_BASELINE}
    verified_map: Dict[str, Dict[str, Any]] = {}

    for url, candidate in _RECORDED_STRUCTURED_CANDIDATES.items():
        entry = by_url.get(url)
        if not entry:
            continue
        page_text = _render_grant_text(entry)
        quotes = candidate.get("quotes", {})

        out: Dict[str, Any] = {
            "evidence_additions": {},
            "verification_additions": {},
        }

        simple_fields = [
            "provider_name",
            "host_country",
            "allowed_degrees",
            "language_requirements",
            "min_work_years",
            "max_age",
            "funding_type",
        ]
        for fname in simple_fields:
            val = candidate.get(fname)
            q = quotes.get(fname)
            if val is not None and q and is_quote_in_text(q, page_text):
                out[fname] = val
                out["evidence_additions"][fname] = q
                out["verification_additions"][fname] = "verified"
            else:
                out[fname] = None
                out["verification_additions"][fname] = "verified" if val is None else "unverified"

        gpa_val = candidate.get("min_gpa_value")
        gpa_scale = candidate.get("min_gpa_scale")
        gpa_quote = quotes.get("min_gpa")
        if gpa_val is not None and gpa_scale and gpa_quote and is_quote_in_text(gpa_quote, page_text):
            out["min_gpa_value"] = gpa_val
            out["min_gpa_scale"] = gpa_scale
            out["min_gpa_normalized_4"] = normalize_gpa_to_4(gpa_val, gpa_scale)
            out["evidence_additions"]["min_gpa"] = gpa_quote
            out["verification_additions"]["min_gpa"] = "verified"
        else:
            out["min_gpa_value"] = None
            out["min_gpa_scale"] = None
            out["min_gpa_normalized_4"] = None
            out["verification_additions"]["min_gpa"] = "verified" if gpa_val is None else "unverified"

        nat_rule = candidate.get("nationality_rule") or {"mode": "unclear", "countries": [], "groups": []}
        nat_quote = quotes.get("nationality_rule") or nat_rule.get("evidence")
        if nat_rule.get("mode") != "unclear" and nat_quote and is_quote_in_text(nat_quote, page_text):
            verified_rule = {
                "mode": nat_rule["mode"],
                "countries": list(nat_rule.get("countries") or []),
                "groups": list(nat_rule.get("groups") or []),
                "evidence": nat_quote,
            }
            out["nationality_rule"] = verified_rule
            out["evidence_additions"]["nationality_rule"] = nat_quote
            out["verification_additions"]["nationality_rule"] = "verified"
            # Consistency assertion with Yemen check
            out["accepts_yemeni_evaluated"] = evaluate_nationality("YE", verified_rule)
        else:
            out["nationality_rule"] = {"mode": "unclear", "countries": [], "groups": [], "evidence": None}
            out["verification_additions"]["nationality_rule"] = "unverified"
            out["accepts_yemeni_evaluated"] = "unclear"

        verified_map[url] = out

    return verified_map


def export_seed_fixtures(target_dir: Optional[Path] = None) -> List[Path]:
    """Write recorded baseline plain-text fixture pages to `seed/fixtures/*.txt`."""
    from seed.seed_db import VERIFIED_TOP10_BASELINE

    out_dir = target_dir or FIXTURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for idx, entry in enumerate(VERIFIED_TOP10_BASELINE, start=1):
        slug = (
            entry["official_url"]
            .replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
            .replace("www.", "")
            .replace(".", "_")
            .replace("-", "_")
        )
        path = out_dir / f"{idx:02d}_{slug}.txt"
        path.write_text(_render_grant_text(entry), encoding="utf-8")
        written.append(path)
    return written

