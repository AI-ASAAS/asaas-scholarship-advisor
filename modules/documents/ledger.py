"""Anti-fabrication Facts Ledger and deterministic draft claim checker (D9).

All normalization, Arabic-Indic/Latin digit folding, bilingual transliteration
matching, GPA conflict detection, and post-generation claim verification happen
deterministically in Python code.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from modules.documents.schemas import FlaggedClaim, LedgerEntry
from modules.matching.gpa import normalize_student_gpa

_ARABIC_INDIC_MAP = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬",
    "01234567890123456789.,",
)

# Common cross-script academic / grant transliteration groups so translated facts
# do not produce false-positive flags while invented facts are still caught.
_TRANSLITERATION_GROUPS: Tuple[Tuple[str, ...], ...] = (
    ("sanaa", "sana'a", "صنعاء", "جامعة صنعاء"),
    ("aden", "عدن", "جامعة عدن"),
    ("taiz", "تعز", "جامعة تعز"),
    ("hodeidah", "hudaydah", "الحديدة", "جامعة الحديدة"),
    ("hadhramout", "hadramout", "حضرموت", "جامعة حضرموت"),
    ("bachelor", "bsc", "ba", "بكالوريوس", "ليسانس"),
    ("master", "msc", "ma", "ماجستير"),
    ("phd", "doctorate", "دكتوراه"),
    ("ielts", "آيلتس", "ايلتس"),
    ("toefl", "توفل"),
    ("computer science", "علوم الحاسوب", "علوم حاسوب", "هندسة البرمجيات", "software engineering"),
    ("public policy", "السياسات العامة", "السياسة العامة"),
    ("engineering", "الهندسة", "هندسة"),
    ("medicine", "الطب", "طب"),
    ("yemen", "اليمن", "يمني", "يمنية"),
    ("scholarship", "منحة"),
    ("chevening", "تشيفنينج"),
    ("daad", "داد"),
    ("fulbright", "فولبرايت"),
    ("turkiye burslari", "المنحة التركية", "تركيا"),
)

_AWARD_PATTERNS = re.compile(
    r"\b("
    r"nobel|pulitzer|fields\s+medal|valedictorian|summa\s+cum\s+laude|magna\s+cum\s+laude|"
    r"gold\s+medal|silver\s+medal|first\s+prize|best\s+student\s+award|honor\s+roll|"
    r"awarded\s+(?:the\s+)?[a-z0-9\s-]{2,30}prize|fellowship\s+winner|"
    r"نوبل|الميدالية\s+الذهبية|الأول\s+على\s+الدفعة|جائزة\s+[\u0621-\u064a]+|وسام\s+[\u0621-\u064a]+|"
    r"شهادة\s+تقدير|مرتبة\s+الشرف(?:\s+الأولى)?"
    r")\b",
    re.IGNORECASE,
)

_RECOMMENDER_VOICE_RE = re.compile(
    r"("
    r"\bI\s+(?:strongly|warmly|enthusiastically|highly)?\s*recommend\s+(?:the\s+applicant|him|her|them)\b|"
    r"\bAs\s+(?:his|her|their)\s+(?:professor|advisor|supervisor|manager)\b|"
    r"\bIn\s+my\s+capacity\s+as\b|"
    r"\bTo\s+whom\s+it\s+may\s+concern\b|"
    r"بصفتي\s+(?:أستاذه|مشرفه|مديره)|"
    r"أوصي\s+بشدة\s+بقبول|"
    r"أشهد\s+بأن\s+الطالب"
    r")",
    re.IGNORECASE,
)

_GPA_EXPLICIT_RE = re.compile(
    r"(?:GPA|ب?(?:ال)?معدل(?:\s+(?:(?:ال)?تراكمي|(?:ال)?عام))?)\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/|من|out\s+of)?\s*([0-9]+(?:\.[0-9]+)?|%)?",
    re.IGNORECASE,
)

_EN_PROPER_PHRASE_RE = re.compile(
    r"\b((?:[A-Z][a-zA-Z'&\.-]{1,})(?:\s+(?:of|for|in|and|the|[A-Z][a-zA-Z'&\.-]{1,})){1,4})\b"
)

_AR_ENTITY_PHRASE_RE = re.compile(
    r"(?<![\w\u0621-\u064a])((?:جامعة|كلية|معهد|شركة|مؤسسة|منظمة|مركز|أكاديمية|بنك)\s+[\u0621-\u064a]{2,}(?:\s+[\u0621-\u064a]{2,}){0,3})"
)

_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([0-9]+(?:\.[0-9]+)?%?)(?![A-Za-z0-9_])")

# Headings / structural labels in drafts that should not trigger false positives as employers/institutions
_SAFE_EN_HEADINGS = {
    "curriculum vitae",
    "academic cv",
    "motivation letter",
    "statement of purpose",
    "personal statement",
    "dear admissions committee",
    "admissions committee",
    "dear professor",
    "polite request message",
    "request message",
    "recommender brief",
    "structure guidance",
    "executive summary",
    "education history",
    "work experience",
    "key achievements",
    "language proficiency",
    "career goals",
    "target scholarship",
    "expected graduation",
    "missing information",
    "required documents",
    "english language",
    "arabic language",
}


def normalize_digits_and_text(value: str) -> str:
    """Fold Arabic-Indic digits to ASCII, strip diacritics, normalize Alef/Ta-Marbuta, lowercase."""
    if not value:
        return ""
    s = value.translate(_ARABIC_INDIC_MAP)
    s = unicodedata.normalize("NFKC", s)
    # Strip Arabic harakat/tashkeel
    s = re.sub(r"[\u064B-\u065F\u0670]", "", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي").replace("ة", "ه").replace("ـ", "")
    s = re.sub(r"\s+", " ", s.lower()).strip()
    return s


def _expand_transliteration_variants(normalized_blob: str) -> Set[str]:
    variants: Set[str] = set()
    for group in _TRANSLITERATION_GROUPS:
        norm_group = [normalize_digits_and_text(item) for item in group]
        if any(item in normalized_blob for item in norm_group):
            variants.update(norm_group)
    return variants


def _extract_numeric_tokens(text: str) -> Set[str]:
    norm = normalize_digits_and_text(text)
    tokens: Set[str] = set()
    for m in _NUMBER_TOKEN_RE.finditer(norm):
        raw = m.group(1).rstrip("%")
        tokens.add(raw)
        try:
            num = float(raw)
            if num.is_integer():
                tokens.add(str(int(num)))
            else:
                tokens.add(f"{num:.2f}".rstrip("0").rstrip("."))
        except ValueError:
            pass
    return tokens


def build_facts_ledger(
    *,
    profile: Optional[Mapping[str, Any]],
    source_text: str,
    grant: Optional[Mapping[str, Any]] = None,
) -> Tuple[List[LedgerEntry], List[FlaggedClaim], List[str]]:
    """Build deterministic verified ledger from student profile + pasted text + grant metadata.

    Returns `(ledger_entries, conflict_flags, missing_info_requests)`.
    """
    entries: List[LedgerEntry] = []
    conflicts: List[FlaggedClaim] = []
    missing: List[str] = []
    idx = 1

    def _add(source: str, category: str, value: Any) -> None:
        nonlocal idx
        if value is None:
            return
        s = str(value).strip()
        if not s:
            return
        norm = normalize_digits_and_text(s)
        variants = sorted(_expand_transliteration_variants(norm) | {norm})
        entries.append(
            LedgerEntry(
                id=f"L{idx}",
                source=source,  # type: ignore[arg-type]
                category=category,
                value=s,
                normalized_tokens=variants,
            )
        )
        idx += 1

    if profile:
        _add("profile", "nationality", profile.get("nationality"))
        _add("profile", "country_of_residence", profile.get("country_of_residence"))
        _add("profile", "current_degree", profile.get("current_degree"))
        _add("profile", "target_degree", profile.get("target_degree"))
        _add("profile", "major", profile.get("major"))
        _add("profile", "expected_graduation_year", profile.get("expected_graduation_year"))
        if profile.get("gpa_raw"):
            _add(
                "profile",
                "gpa",
                f"{profile.get('gpa_raw')} / {profile.get('gpa_scale') or ''}".strip(" /"),
            )
        if profile.get("work_experience_years") is not None:
            _add("profile", "work_experience_years", profile.get("work_experience_years"))
        if profile.get("age_years") is not None:
            _add("profile", "age_years", profile.get("age_years"))
        if profile.get("publications_count"):
            _add("profile", "publications_count", profile.get("publications_count"))
        for lang_item in profile.get("languages") or []:
            if isinstance(lang_item, Mapping):
                parts = [str(lang_item.get("language") or "")]
                if lang_item.get("test_name"):
                    parts.append(str(lang_item["test_name"]))
                if lang_item.get("score") is not None:
                    parts.append(str(lang_item["score"]))
                if lang_item.get("self_assessed_cefr"):
                    parts.append(str(lang_item["self_assessed_cefr"]))
                _add("profile", "language", " ".join(p for p in parts if p))
        for country in profile.get("target_countries") or []:
            _add("profile", "target_country", country)
        for field in profile.get("target_fields") or []:
            _add("profile", "target_field", field)
        for note in profile.get("experience_notes") or []:
            _add("profile", "experience_note", note)

        if profile.get("expected_graduation_year") is None:
            missing.append("أضف سنة التخرج المتوقعة أو الفعلية (Expected Graduation Year).")
        if not (profile.get("languages") or []):
            missing.append("أضف شهادة اللغة أو مستواك اللغوي التقديري (Language Score).")

    # Store pasted text facts cleanly sentence-by-sentence
    clean_source = (source_text or "").strip()
    if clean_source:
        _add("pasted_text", "raw_text", clean_source)
        for sentence in re.split(r"[\n\r.؛!؟]+", clean_source):
            st = sentence.strip()
            if len(st) >= 3:
                _add("pasted_text", "statement", st)

    if grant:
        _add("grant", "title", grant.get("title"))
        _add("grant", "provider_name", grant.get("provider_name"))
        _add("grant", "host_country", grant.get("host_country"))
        _add("grant", "official_url", grant.get("official_url"))
        if grant.get("deadline"):
            _add("grant", "deadline", grant.get("deadline"))
        for req_doc in grant.get("required_documents") or []:
            _add("grant", "required_document", req_doc)
        for crit in grant.get("criteria") or []:
            _add("grant", "criteria", crit)

    # Conflict detection: GPA stated in pasted source text vs saved profile
    if profile and profile.get("gpa_normalized_4") is not None and clean_source:
        norm_source = normalize_digits_and_text(clean_source)
        prof_norm_4 = float(profile["gpa_normalized_4"])
        for match in _GPA_EXPLICIT_RE.finditer(norm_source):
            val_str, scale_raw = match.group(1), match.group(2)
            scale = None
            if scale_raw == "%" or ("%" in match.group(0)):
                scale = "100"
            elif scale_raw in {"4", "4.0", "5", "5.0", "100"}:
                scale = "4.0" if scale_raw in {"4", "4.0"} else ("5.0" if scale_raw in {"5", "5.0"} else "100")
            else:
                # Infer scale safely when clear
                try:
                    v = float(val_str)
                    if v <= 4.0 and (profile.get("gpa_scale") == "4.0"):
                        scale = "4.0"
                    elif 5.0 < v <= 100.0 and (profile.get("gpa_scale") == "100"):
                        scale = "100"
                except ValueError:
                    pass
            if scale:
                try:
                    pasted_4, _ = normalize_student_gpa(val_str, scale)
                except ValueError:
                    pasted_4 = None
                if pasted_4 is not None and abs(pasted_4 - prof_norm_4) >= 0.08:
                    conflicts.append(
                        FlaggedClaim(
                            id=f"C{len(conflicts) + 1}",
                            claim_text=match.group(0).strip(),
                            category="conflict",
                            reason_ar=(
                                f"تعارض في المعدل: النص المُلصق يذكر ({val_str}) بينما ملفك الشخصي مسجّل به ({profile.get('gpa_raw')}). "
                                "يُرجى التعديل أو التأكيد أيهما الصحيح."
                            ),
                            reason_en=(
                                f"GPA conflict: pasted text says '{val_str}' whereas your profile states '{profile.get('gpa_raw')}'."
                            ),
                            status="needs_confirmation",
                        )
                    )

    return entries, conflicts, missing


def verify_draft_against_ledger(
    *,
    draft_text: str,
    doc_type: str,
    ledger: Sequence[LedgerEntry],
    existing_conflicts: Optional[Sequence[FlaggedClaim]] = None,
) -> List[FlaggedClaim]:
    """Deterministic post-generation verifier flagging any fact absent from the ledger."""
    flagged: List[FlaggedClaim] = list(existing_conflicts or [])
    seen_texts: Set[str] = {normalize_digits_and_text(c.claim_text) for c in flagged}

    # Build normalized verified corpus from student profile + pasted text + grant metadata
    corpus_parts: List[str] = []
    student_only_parts: List[str] = []
    for entry in ledger:
        corpus_parts.append(entry.value)
        corpus_parts.extend(entry.normalized_tokens)
        if entry.source in {"profile", "pasted_text"}:
            student_only_parts.append(entry.value)
            student_only_parts.extend(entry.normalized_tokens)

    corpus_norm = normalize_digits_and_text(" \n ".join(corpus_parts))
    corpus_variants = corpus_norm + " " + " ".join(_expand_transliteration_variants(corpus_norm))
    student_norm = normalize_digits_and_text(" \n ".join(student_only_parts))

    allowed_numbers = _extract_numeric_tokens(corpus_norm)
    # Strip ordered list prefixes like "1." / "2)" at start of lines from number checks
    draft_for_numbers = re.sub(r"(?m)^\s*[0-9\u0660-\u0669]{1,2}[.)]\s+", "", draft_text or "")
    # Also strip structural Arabic bullets like "1-" at start of line
    draft_for_numbers = re.sub(r"(?m)^\s*[0-9\u0660-\u0669]{1,2}-\s+", "", draft_for_numbers)

    def _add_flag(claim_text: str, category: str, reason_ar: str, reason_en: str) -> None:
        key = normalize_digits_and_text(claim_text)
        if not key or key in seen_texts:
            return
        seen_texts.add(key)
        flagged.append(
            FlaggedClaim(
                id=f"FC{len(flagged) + 1}",
                claim_text=claim_text.strip(),
                category=category,  # type: ignore[arg-type]
                reason_ar=reason_ar,
                reason_en=reason_en,
                status="needs_confirmation",
            )
        )

    # 1. Check all numbers, GPAs, percentages, scores, and 4-digit years
    for m in _NUMBER_TOKEN_RE.finditer(normalize_digits_and_text(draft_for_numbers)):
        raw_num = m.group(1)
        clean_num = raw_num.rstrip("%")
        if clean_num in allowed_numbers:
            continue
        try:
            fnum = float(clean_num)
            if fnum.is_integer() and str(int(fnum)) in allowed_numbers:
                continue
        except ValueError:
            pass
        cat = "date" if re.fullmatch(r"(?:19|20)\d{2}", clean_num) else "number"
        _add_flag(
            raw_num,
            cat,
            f"الرقم أو التاريخ ({raw_num}) غير موثق في ملفك أو النص الذي زوّدتنا به ويحتاج تأكيدك.",
            f"Number or date '{raw_num}' is not present in your verified facts ledger and needs confirmation.",
        )

    # 2. Check awards / honors claims strictly against student-supplied facts (never allow unverified awards)
    draft_norm = normalize_digits_and_text(draft_text)
    for m in _AWARD_PATTERNS.finditer(normalize_digits_and_text(draft_text).translate(_ARABIC_INDIC_MAP)):
        phrase = m.group(0).strip()
        phrase_norm = normalize_digits_and_text(phrase)
        # Allow if phrase or its core award noun is present in student profile/pasted text
        core_words = [w for w in phrase_norm.split() if len(w) > 3]
        in_student = phrase_norm in student_norm or (
            len(core_words) >= 2 and all(w in student_norm for w in core_words)
        )
        if not in_student:
            _add_flag(
                phrase,
                "award",
                f"ادعاء جائزة أو تكريم ({phrase}) غير وارد في ملفك أو نصك ويحتاج تأكيدك أو حذفه.",
                f"Award/honor claim '{phrase}' is not found in your supplied profile or text.",
            )

    # 3. Check English multi-word Proper Entities (universities, employers, organizations)
    for m in _EN_PROPER_PHRASE_RE.finditer(draft_text or ""):
        phrase = m.group(1).strip()
        p_norm = normalize_digits_and_text(phrase)
        if p_norm in _SAFE_EN_HEADINGS or len(p_norm) < 4:
            continue
        words = [w for w in p_norm.split() if len(w) >= 3 and w not in {"the", "for", "and", "of", "in", "to"}]
        if p_norm in corpus_variants:
            continue
        # Allow if every significant token appears across corpus + bilingual transliterations
        if words and all(w in corpus_variants for w in words):
            continue
        # Focus entity flag on organizations/institutions/employers (skip generic multi-cap headings <=2 short words unless institutional keyword present)
        inst_hint = any(
            kw in p_norm
            for kw in ("university", "college", "institute", "company", "corp", "inc", "foundation", "bank", "ministry", "hospital", "labs", "fellowship", "prize", "award")
        )
        if inst_hint or len(words) >= 2:
            cat = "employer" if any(k in p_norm for k in ("company", "corp", "inc", "ltd", "llc")) else "institution"
            _add_flag(
                phrase,
                cat,
                f"الاسم أو الجهة ({phrase}) غير موجودة في سجل حقائقك وتحتاج تأكيدك.",
                f"Named institution or entity '{phrase}' is not present in your verified facts ledger.",
            )

    # 4. Check Arabic named institutions/companies (`جامعة X`, `شركة Y`, `مؤسسة Z`)
    for m in _AR_ENTITY_PHRASE_RE.finditer(draft_text or ""):
        phrase = m.group(1).strip()
        p_norm = normalize_digits_and_text(phrase)
        tokens = [w for w in p_norm.split() if len(w) >= 3]
        if p_norm in corpus_variants:
            continue
        if tokens and all(w in corpus_variants for w in tokens):
            continue
        _add_flag(
            phrase,
            "institution",
            f"الجهة أو المؤسسة ({phrase}) غير موجودة في سجل حقائقك وتحتاج تأكيدك.",
            f"Institution or organization '{phrase}' is not verified in your facts ledger.",
        )

    # 5. Guard against recommender-voice ready-to-sign letter when doc_type == recommendation_support
    if doc_type == "recommendation_support":
        rm = _RECOMMENDER_VOICE_RE.search(draft_text or "")
        if rm:
            _add_flag(
                rm.group(0).strip(),
                "recommendation_voice",
                "تحذير: يُمنع صياغة خطاب توصية جاهز بصوت الموصي؛ يجب تقديم رسالة طلب وملخص للموصي فقط.",
                "Recommender-voice endorsement phrase detected; recommendation support must not impersonate the recommender.",
            )

    return flagged
