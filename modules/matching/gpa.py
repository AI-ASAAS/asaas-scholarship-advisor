"""Deterministic GPA scale normalization from versioned config (D6)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SUPPORTED_GPA_SCALES = {"4.0", "5.0", "100", "label"}
_CONFIG_PATH = Path(__file__).resolve().parent / "gpa_scales.json"


@lru_cache(maxsize=1)
def get_gpa_scales_config() -> Dict[str, Any]:
    """Load and cache the versioned GPA conversion table."""
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def normalize_gpa_to_4(value: Optional[float], scale: Optional[str]) -> Optional[float]:
    """Normalize a numeric GPA threshold onto the canonical 4.0 scale."""
    if value is None or scale is None:
        return None
    normalized_scale = scale.strip().lower()
    cfg = get_gpa_scales_config()

    if normalized_scale == "4.0":
        return round(max(0.0, min(4.0, float(value))), 2)
    if normalized_scale == "5.0":
        return round(max(0.0, min(4.0, (float(value) / 5.0) * 4.0)), 2)
    if normalized_scale == "100":
        pct = float(value)
        for rule in cfg["percentage_breakpoints"]:
            if pct >= float(rule["min"]):
                return float(rule["gpa_4"])
        return 1.00
    return None


def normalize_student_gpa(
    gpa_raw: Optional[str],
    gpa_scale: Optional[str],
) -> Tuple[Optional[float], bool]:
    """Parse and normalize student GPA onto 4.0 scale.

    Returns:
        (normalized_gpa_4, is_assumed_yemeni_label)
    Raises:
        ValueError: if gpa_raw or gpa_scale is syntactically invalid or out of bounds.
    """
    if (gpa_raw is None or not gpa_raw.strip()) and gpa_scale is None:
        return None, False
    if (gpa_raw is None or not gpa_raw.strip()) or gpa_scale is None:
        raise ValueError("يجب تحديد قيمة المعدل والمقياس معاً أو تركهما فارغين.")

    scale = gpa_scale.strip().lower()
    if scale not in SUPPORTED_GPA_SCALES:
        raise ValueError("مقياس المعدل غير مدعوم.")

    raw = gpa_raw.strip()
    if scale == "label":
        labels: Dict[str, float] = get_gpa_scales_config()["yemeni_labels"]
        key = " ".join(raw.lower().split())
        if key not in labels:
            raise ValueError(
                "التقدير غير معروف؛ استخدم: ممتاز، جيد جداً، جيد، مقبول، ضعيف."
            )
        return float(labels[key]), True

    try:
        numeric = float(raw)
    except ValueError as exc:
        raise ValueError("قيمة المعدل يجب أن تكون رقماً صالحاً لهذا المقياس.") from exc

    upper_bound = {"4.0": 4.0, "5.0": 5.0, "100": 100.0}[scale]
    if numeric < 0.0 or numeric > upper_bound:
        raise ValueError(f"قيمة المعدل لمقياس {scale} يجب أن تكون بين 0 و {upper_bound}.")

    return normalize_gpa_to_4(numeric, scale), False
