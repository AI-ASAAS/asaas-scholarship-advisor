"""Generic nationality eligibility evaluation (D5).

Yemeni students are first-class defaults in the UI, while eligibility
evaluation operates purely on generic ISO-3166 alpha-2 country codes
and code-owned country group mappings.
"""

from typing import Any, Dict, FrozenSet, Literal, Mapping, Optional

NationalityResult = Literal["yes", "no", "unclear"]

COUNTRY_ALIASES: Dict[str, str] = {
    "YE": "YE",
    "YEMEN": "YE",
    "YEMENI": "YE",
    "اليمن": "YE",
    "يمني": "YE",
    "TR": "TR",
    "TURKEY": "TR",
    "TÜRKIYE": "TR",
    "GB": "GB",
    "UK": "GB",
    "UNITED KINGDOM": "GB",
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "DE": "DE",
    "GERMANY": "DE",
    "FR": "FR",
    "FRANCE": "FR",
    "RO": "RO",
    "ROMANIA": "RO",
    "HU": "HU",
    "HUNGARY": "HU",
    "CN": "CN",
    "CHINA": "CN",
    "RU": "RU",
    "RUSSIA": "RU",
    "SA": "SA",
    "SAUDI ARABIA": "SA",
    "السعودية": "SA",
    "EG": "EG",
    "EGYPT": "EG",
    "مصر": "EG",
    "JO": "JO",
    "JORDAN": "JO",
    "الأردن": "JO",
    "AE": "AE",
    "UAE": "AE",
    "الإمارات": "AE",
    "KW": "KW",
    "KUWAIT": "KW",
    "الكويت": "KW",
    "QA": "QA",
    "QATAR": "QA",
    "قطر": "QA",
    "OM": "OM",
    "OMAN": "OM",
    "عمان": "OM",
    "BH": "BH",
    "BAHRAIN": "BH",
    "البحرين": "BH",
    "IQ": "IQ",
    "IRAQ": "IQ",
    "العراق": "IQ",
    "SY": "SY",
    "SYRIA": "SY",
    "سوريا": "SY",
    "LB": "LB",
    "LEBANON": "LB",
    "لبنان": "LB",
    "PS": "PS",
    "PALESTINE": "PS",
    "فلسطين": "PS",
    "SD": "SD",
    "SUDAN": "SD",
    "السودان": "SD",
    "MA": "MA",
    "MOROCCO": "MA",
    "المغرب": "MA",
    "DZ": "DZ",
    "ALGERIA": "DZ",
    "الجزائر": "DZ",
    "TN": "TN",
    "TUNISIA": "TN",
    "تونس": "TN",
    "MY": "MY",
    "MALAYSIA": "MY",
    "ماليزيا": "MY",
    "ID": "ID",
    "INDONESIA": "ID",
    "إندونيسيا": "ID",
    "PK": "PK",
    "PAKISTAN": "PK",
    "باكستان": "PK",
    "IN": "IN",
    "INDIA": "IN",
    "الهند": "IN",
    "JP": "JP",
    "JAPAN": "JP",
    "اليابان": "JP",
}

EU_MEMBERS: FrozenSet[str] = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
        "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    }
)

GCC_MEMBERS: FrozenSet[str] = frozenset({"AE", "BH", "KW", "OM", "QA", "SA"})

ISDB_MEMBERS: FrozenSet[str] = frozenset(
    {
        "AF", "AL", "DZ", "AZ", "BH", "BD", "BJ", "BN", "BF", "CM",
        "TD", "KM", "CI", "DJ", "EG", "GA", "GM", "GN", "GW", "GY",
        "ID", "IR", "IQ", "JO", "KZ", "KW", "KG", "LB", "LY", "MY",
        "MV", "ML", "MR", "MA", "MZ", "NE", "NG", "OM", "PK", "PS",
        "QA", "SA", "SN", "SL", "SO", "SD", "SR", "SY", "TJ", "TG",
        "TN", "TR", "TM", "UG", "AE", "UZ", "YE",
    }
)

# UNCTAD / OECD DAC developing economies snapshot for common global grant schemes.
DEVELOPING_COUNTRIES: FrozenSet[str] = ISDB_MEMBERS | frozenset(
    {
        "AO", "AR", "AM", "BO", "BR", "KH", "CV", "CL", "CN", "CO",
        "CR", "CU", "DO", "EC", "SV", "ET", "FJ", "GE", "GH", "GT",
        "HN", "IN", "JM", "KE", "LA", "LR", "MG", "MW", "MX", "MN",
        "MM", "NA", "NP", "NI", "PA", "PG", "PY", "PE", "PH", "RW",
        "LK", "TH", "TL", "TZ", "UA", "UY", "VE", "VN", "ZM", "ZW",
    }
)

BELT_AND_ROAD_MEMBERS: FrozenSet[str] = ISDB_MEMBERS | frozenset(
    {
        "AM", "AR", "BY", "BO", "CL", "CN", "CR", "CU", "EC", "ET",
        "GE", "GH", "GR", "HU", "KE", "LA", "MG", "MN", "MM", "NA",
        "NP", "NZ", "PA", "PE", "PH", "PL", "PT", "RO", "RU", "RW",
        "RS", "SG", "ZA", "KR", "LK", "TH", "TZ", "UA", "UY", "VE",
        "VN", "ZM", "ZW",
    }
)

COUNTRY_GROUPS: Dict[str, FrozenSet[str]] = {
    "eu": EU_MEMBERS,
    "gcc": GCC_MEMBERS,
    "isdb_members": ISDB_MEMBERS,
    "developing_countries": DEVELOPING_COUNTRIES,
    "belt_and_road": BELT_AND_ROAD_MEMBERS,
}


def normalize_country_code(raw: Optional[str]) -> Optional[str]:
    """Normalize an ISO-3166 alpha-2 code or known country name to uppercase alpha-2."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().upper()
    if cleaned in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[cleaned]
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned
    return None


def _in_group(code: str, group_name: str) -> Optional[bool]:
    """Check membership in a code-owned group. Returns None if group is unknown."""
    key = group_name.strip().lower()
    if key == "non_eu":
        return code not in EU_MEMBERS
    members = COUNTRY_GROUPS.get(key)
    if members is None:
        return None
    return code in members


def evaluate_nationality(
    nationality_code: Optional[str],
    rule: Optional[Mapping[str, Any]],
) -> NationalityResult:
    """Evaluate whether a nationality satisfies a structured nationality rule.

    Returns strictly one of: "yes", "no", "unclear".
    """
    code = normalize_country_code(nationality_code)
    if not code or not rule or not isinstance(rule, Mapping):
        return "unclear"

    mode = str(rule.get("mode") or "unclear").strip().lower()
    raw_countries = rule.get("countries") or []
    raw_groups = rule.get("groups") or []

    countries = {
        norm
        for item in raw_countries
        if (norm := normalize_country_code(str(item))) is not None
    }
    groups = [str(g).strip().lower() for g in raw_groups if str(g).strip()]

    if mode == "unclear":
        return "unclear"

    if mode == "all":
        # Open to all unless explicitly excluded in countries
        if code in countries:
            return "no"
        return "yes"

    if mode == "exclude":
        if code in countries:
            return "no"
        for group_name in groups:
            membership = _in_group(code, group_name)
            if membership is True:
                return "no"
            if membership is None:
                return "unclear"
        return "yes"

    if mode in {"include", "group"}:
        if code in countries:
            return "yes"
        has_unknown_group = False
        for group_name in groups:
            membership = _in_group(code, group_name)
            if membership is True:
                return "yes"
            if membership is None:
                has_unknown_group = True
        if has_unknown_group:
            return "unclear"
        if countries or groups:
            return "no"
        return "unclear"

    return "unclear"
