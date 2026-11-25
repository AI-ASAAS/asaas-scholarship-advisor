"""Deterministic plan generator: ordering, checklists, backward timeline, conflicts, and .ics export."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from core.config import settings
from modules.documents.service import compute_deterministic_gaps
from modules.matching.schemas import GrantMatchResult
from modules.plans.schemas import (
    DeadlineConflict,
    PlanChecklistItem,
    PlanMilestone,
    UrgencyStatusLiteral,
)

_PACING_NOTE_AR = "توجيه مقترح لتوزيع الوقت، وليس شرطاً رسمياً"
_PACING_NOTE_EN = "Suggested pacing, not an official requirement"

_OFFSET_LABELS = {
    56: ("مراجعة الشروط وتجهيز مسودة السيرة الذاتية ورسالة الدافع", "Review eligibility & draft CV / motivation letter"),
    42: ("التواصل مع الموصين ومراجعة متطلبات اللغة", "Contact recommenders & check language score readiness"),
    28: ("تجهيز الوثائق المطلوبة وترجمتها ومراجعتها", "Gather, translate, and review required documents"),
    14: ("استكمال المسودة النهائية والتحقق من بوابة التقديم الرسمية", "Finalize drafts and verify official portal form"),
    7: ("مراجعة نهائية شاملة قبل أسبوع من الإغلاق", "Final review pass 7 days before deadline"),
    3: ("الرفع والتسليم المبكر تفادياً لأي عطل تقني", "Early submission recommended to avoid portal issues"),
}


def parse_milestone_offsets(raw: Optional[str] = None) -> List[int]:
    src = raw if raw is not None else settings.PLANS_MILESTONE_OFFSETS_RAW
    offsets: List[int] = []
    for part in str(src).split(","):
        s = part.strip()
        if s.isdigit() and int(s) > 0:
            offsets.append(int(s))
    return sorted(set(offsets), reverse=True) or [42, 28, 14, 7, 3]


def local_today(tz_name: Optional[str] = None, now_utc: Optional[datetime] = None) -> date:
    """Resolve current date cleanly in the configured timezone around midnight."""
    tz = ZoneInfo((tz_name or settings.PLANS_TIMEZONE or "UTC").strip())
    base_utc = now_utc or datetime.now(timezone.utc)
    if base_utc.tzinfo is None:
        base_utc = base_utc.replace(tzinfo=timezone.utc)
    return base_utc.astimezone(tz).date()


def classify_deadline_urgency(
    deadline: Optional[date],
    *,
    today: date,
    soon_days: Optional[int] = None,
) -> Tuple[Optional[int], UrgencyStatusLiteral]:
    if deadline is None:
        return None, "no_deadline"
    delta = (deadline - today).days
    window = soon_days if soon_days is not None else settings.PLANS_SOON_DUE_DAYS
    if delta < 0:
        return delta, "overdue"
    if delta == 0:
        return delta, "due_today"
    if delta <= window:
        return delta, "due_soon"
    return delta, "upcoming"


def sort_plan_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order plan entries: eligible by Phase 3 match % desc, ties nearest deadline; ineligible last."""

    def _key(entry: Dict[str, Any]) -> Tuple[Any, ...]:
        eligible = bool(entry.get("eligible", False))
        match_pct = float(entry.get("match_percentage") or 0.0)
        coverage_pct = float(entry.get("coverage_percentage") or 0.0)
        dl: Optional[date] = entry.get("deadline_date")
        dl_ord = dl.toordinal() if isinstance(dl, date) else 10**9
        grant_id = int(entry.get("grant_id") or 0)
        if eligible:
            return (0, -match_pct, -coverage_pct, dl_ord, grant_id)
        return (1, dl_ord, grant_id)

    return sorted(entries, key=_key)


def build_grant_checklist(
    *,
    profile: Mapping[str, Any],
    grant: Mapping[str, Any],
    existing_items: Optional[Sequence[Mapping[str, Any]]] = None,
    reference_date: date,
) -> List[PlanChecklistItem]:
    """Generate deterministic checklist from verified grant data + Phase 5 student gaps."""
    prior_status = {
        str(it.get("id")): str(it.get("status") or "todo")
        for it in (existing_items or [])
        if it.get("id") and it.get("status") in {"todo", "in_progress", "done"}
    }
    official_url = str(grant.get("official_url") or "")
    evidence = grant.get("evidence") or {}
    items: List[PlanChecklistItem] = []

    def _status(item_id: str) -> str:
        return prior_status.get(item_id, "todo")

    # 1. Required documents from verified record (never invented when omitted)
    req_docs = [str(d).strip() for d in (grant.get("required_documents") or []) if str(d).strip()]
    if req_docs:
        doc_ev = evidence.get("required_documents")
        for i, doc_name in enumerate(req_docs, start=1):
            iid = f"doc_{i}"
            items.append(
                PlanChecklistItem(
                    id=iid,
                    category="document",
                    label_ar=f"تجهيز وثيقة: {doc_name}",
                    label_en=f"Prepare document: {doc_name}",
                    evidence_quote=doc_ev if isinstance(doc_ev, str) else None,
                    official_url=official_url,
                    status=_status(iid),  # type: ignore[arg-type]
                )
            )
    else:
        iid = "doc_not_stated"
        items.append(
            PlanChecklistItem(
                id=iid,
                category="missing_official",
                label_ar="الوثائق المطلوبة غير منصوص عليها في الصفحة الرسمية — راجع البوابة الرسمية",
                label_en="Required documents not stated on the official page — check official portal",
                official_url=official_url,
                is_not_stated_officially=True,
                status=_status(iid),  # type: ignore[arg-type]
            )
        )

    # 2. Application steps from grant.how_to_apply (kept verbatim; never invented)
    how_to = str(grant.get("how_to_apply") or "").strip()
    how_ev = evidence.get("how_to_apply")
    if how_to:
        iid = "step_apply"
        items.append(
            PlanChecklistItem(
                id=iid,
                category="application_step",
                label_ar=f"خطوات التقديم الرسمية: {how_to}",
                label_en=f"Official application steps: {how_to}",
                evidence_quote=how_ev if isinstance(how_ev, str) else None,
                official_url=official_url,
                status=_status(iid),  # type: ignore[arg-type]
            )
        )
    else:
        iid = "step_not_stated"
        items.append(
            PlanChecklistItem(
                id=iid,
                category="missing_official",
                label_ar="تفاصيل خطوات التقديم غير منصوص عليها في الصفحة الرسمية — راجع البوابة الرسمية",
                label_en="Application steps not stated on the official page — check official portal",
                official_url=official_url,
                is_not_stated_officially=True,
                status=_status(iid),  # type: ignore[arg-type]
            )
        )

    # 3. Student-specific gaps from Phase 5 engine
    gaps = compute_deterministic_gaps(profile, [dict(grant)], reference_date=reference_date)
    for g in gaps:
        iid = f"gap_{g.gap_type}"
        items.append(
            PlanChecklistItem(
                id=iid,
                category="gap",
                label_ar=g.title_ar,
                label_en=g.title_en,
                detail_ar=g.evidence_ar,
                detail_en=g.evidence_en,
                official_url=official_url,
                is_assumption=g.is_assumption,
                status=_status(iid),  # type: ignore[arg-type]
            )
        )

    return items


def build_backward_milestones(
    deadline: Optional[date],
    *,
    today: date,
    offsets: Optional[List[int]] = None,
    soon_days: Optional[int] = None,
) -> List[PlanMilestone]:
    """Compute backward milestones across month/year boundaries with suggested-pacing labels."""
    if deadline is None:
        return []
    offs = offsets if offsets is not None else parse_milestone_offsets()
    soon = soon_days if soon_days is not None else settings.PLANS_SOON_DUE_DAYS
    milestones: List[PlanMilestone] = []
    for off in sorted(offs, reverse=True):
        m_date = deadline - timedelta(days=off)
        delta = (m_date - today).days
        if delta < 0:
            st = "overdue"
        elif delta == 0:
            st = "due_today"
        elif delta <= soon:
            st = "due_soon"
        else:
            st = "upcoming"
        default_ar = f"محطة إعداد مقترحة قبل {off} يوماً من الإغلاق"
        default_en = f"Suggested prep milestone ({off} days before deadline)"
        lbl_ar, lbl_en = _OFFSET_LABELS.get(off, (default_ar, default_en))
        milestones.append(
            PlanMilestone(
                offset_days=off,
                due_date=m_date.isoformat(),
                days_from_today=delta,
                status=st,  # type: ignore[arg-type]
                label_ar=lbl_ar,
                label_en=lbl_en,
                pacing_note_ar=_PACING_NOTE_AR,
                pacing_note_en=_PACING_NOTE_EN,
            )
        )
    return milestones


def detect_deadline_conflicts(
    dated_grants: Sequence[Tuple[int, str, date]],
    *,
    window_days: Optional[int] = None,
) -> List[DeadlineConflict]:
    """Flag clusters of >= 2 grants whose deadlines fall within `window_days` days."""
    window = window_days if window_days is not None else settings.PLANS_CONFLICT_WINDOW_DAYS
    ordered = sorted(dated_grants, key=lambda x: (x[2], x[0]))
    if len(ordered) < 2:
        return []

    conflicts: List[DeadlineConflict] = []
    cluster: List[Tuple[int, str, date]] = [ordered[0]]

    def _flush(group: List[Tuple[int, str, date]]) -> None:
        if len(group) < 2:
            return
        start_d = group[0][2]
        end_d = group[-1][2]
        span = (end_d - start_d).days
        titles = [g[1] for g in group]
        conflicts.append(
            DeadlineConflict(
                conflict_id=f"CF{len(conflicts) + 1}",
                start_date=start_d.isoformat(),
                end_date=end_d.isoformat(),
                span_days=span,
                grant_ids=[g[0] for g in group],
                grant_titles=titles,
                message_ar=(
                    f"تداخل مواعيد: لديك {len(group)} منح تغلق خلال {span} يوماً "
                    f"({start_d.isoformat()} إلى {end_d.isoformat()}): {', '.join(titles)}."
                ),
                message_en=(
                    f"Deadline cluster: {len(group)} scholarships close within {span} days "
                    f"({start_d.isoformat()} to {end_d.isoformat()}): {', '.join(titles)}."
                ),
            )
        )

    for item in ordered[1:]:
        if (item[2] - cluster[-1][2]).days <= window:
            cluster.append(item)
        else:
            _flush(cluster)
            cluster = [item]
    _flush(cluster)
    return conflicts


def _ics_escape(val: str) -> str:
    return (
        val.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold_ics_line(line: str) -> str:
    # RFC 5545 folds physical lines exceeding 75 octets using CRLF + single space.
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    chunks: List[str] = []
    cur = bytearray()
    for ch in line:
        ch_bytes = ch.encode("utf-8")
        limit = 75 if not chunks else 74
        if len(cur) + len(ch_bytes) > limit:
            chunks.append(cur.decode("utf-8"))
            cur = bytearray(ch_bytes)
        else:
            cur.extend(ch_bytes)
    if cur:
        chunks.append(cur.decode("utf-8"))
    return "\r\n ".join(chunks)


def build_ics_calendar(
    *,
    plan_id: Optional[int],
    items: Sequence[Dict[str, Any]],
    now_utc: Optional[datetime] = None,
) -> str:
    """Generate RFC 5545 all-day iCalendar file containing scholarship deadlines & official links."""
    ts = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines: List[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ASAAS AI//Scholarship Application Plan//AR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    pid = plan_id or 0
    for it in items:
        dl: Optional[date] = it.get("deadline_date")
        if not isinstance(dl, date):
            continue
        end_d = dl + timedelta(days=1)  # RFC 5545 exclusive DTEND for all-day VALUE=DATE
        gid = int(it["grant_id"])
        title = str(it.get("title") or "")
        url = str(it.get("official_url") or "")
        rank = int(it.get("priority_rank") or 1)
        desc = (
            f"الأولوية #{rank} | التطابق: {it.get('match_percentage', 0)}%\n"
            f"البوابة الرسمية: {url}\n"
            "يرجى مراجعة الموقع الرسمي لتأكيد الموعد النهائي."
        )
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:asaas-plan-{pid}-grant-{gid}@asaas.ai",
                f"DTSTAMP:{ts}",
                f"DTSTART;VALUE=DATE:{dl.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{end_d.strftime('%Y%m%d')}",
                _fold_ics_line(f"SUMMARY:{_ics_escape(f'آخر موعد للمنحة: {title}')}"),
                _fold_ics_line(f"DESCRIPTION:{_ics_escape(desc)}"),
                _fold_ics_line(f"URL:{url}"),
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
