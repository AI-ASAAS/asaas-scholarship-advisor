"""Monitor Service (Task 9).

Periodic checker that:
1. Re-visits official URLs of published scholarships to verify data freshness.
2. Detects page modifications via SHA-256 content hashes.
3. Records detected field changes into UpdateLog without auto-overwriting published data.
4. Dispatches closing alerts at 7 days and 3 days before deadline.
5. Automatically marks elapsed grants as EXPIRED.
6. Operates on-demand or as a recurring background daemon via APScheduler.
"""

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import httpx
from sqlalchemy.orm import Session

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import settings
from core.db import get_db, init_db
from core.models import Grant, GrantStatus
from core.repository import log_update, mark_expired
from ingestion_sub_agent import compute_content_hash, fetch_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def send_alert(alert_type: str, title: str, details: str, webhook_url: Optional[str] = None) -> Dict[str, Any]:
    """Issue a structured alert via logging and optional webhook."""
    alert_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alert_type": alert_type,
        "title": title,
        "details": details,
    }

    # Console Alert Output
    logger.warning("🚨 [MONITOR ALERT: %s] %s -> %s", alert_type, title, details)

    # Optional Webhook Notification
    target_url = webhook_url or settings.ALERT_WEBHOOK_URL
    if target_url:
        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(target_url, json=alert_payload)
        except Exception as exc:
            logger.error("Failed to send alert to webhook: %s", exc)

    return alert_payload


def check_imminent_deadlines(
    db: Session,
    reference_date: Optional[date] = None,
    webhook_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Scan published scholarships and trigger closing / expiration alerts.

    Thresholds:
    - 7 days before deadline: Standard closing alert
    - 3 days before deadline: URGENT closing alert
    - < 0 days (past deadline): Auto-mark as EXPIRED and log update
    """
    ref_date = reference_date or date.today()
    alerts: List[Dict[str, Any]] = []

    published_grants = db.query(Grant).filter(Grant.status == GrantStatus.PUBLISHED).all()

    for grant in published_grants:
        if not grant.deadline:
            continue

        days_remaining = (grant.deadline - ref_date).days

        if days_remaining < 0:
            # Grant has expired
            mark_expired(db, grant.id)
            log_update(
                db=db,
                grant_id=grant.id,
                field_name="status",
                old_value=GrantStatus.PUBLISHED.value,
                new_value=GrantStatus.EXPIRED.value,
                notified=True,
            )
            alert = send_alert(
                alert_type="GRANT_EXPIRED",
                title=grant.title,
                details=f"Grant expired on {grant.deadline} ({abs(days_remaining)} days ago). Status set to EXPIRED.",
                webhook_url=webhook_url,
            )
            alerts.append(alert)

        elif days_remaining == 3:
            # 3 days urgent alert
            alert = send_alert(
                alert_type="CLOSING_SOON_URGENT",
                title=grant.title,
                details=f"URGENT: Application deadline closes in 3 days ({grant.deadline})!",
                webhook_url=webhook_url,
            )
            alerts.append(alert)

        elif days_remaining == 7:
            # 7 days warning alert
            alert = send_alert(
                alert_type="CLOSING_SOON_7_DAYS",
                title=grant.title,
                details=f"Notice: Application deadline closes in 7 days ({grant.deadline}).",
                webhook_url=webhook_url,
            )
            alerts.append(alert)

    db.flush()
    return alerts


def check_grant_updates(
    grant: Grant,
    db: Session,
    page_fetcher: Optional[Callable[[str], str]] = None,
    extracted_deadline_override: Optional[date] = None,
    webhook_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Check a single grant's official URL for content/deadline modifications.

    Args:
        grant: The Grant instance to verify.
        db: SQLAlchemy Session.
        page_fetcher: Custom fetcher callable(url) -> text (useful for mocking).
        extracted_deadline_override: Override new deadline (for testing without full LLM call).
        webhook_url: Optional webhook URL for alerts.

    Returns:
        Dict describing detected changes, or None if unchanged.
    """
    try:
        if page_fetcher:
            current_text = page_fetcher(grant.official_url)
        else:
            current_text, _ = fetch_page(grant.official_url)
    except Exception as exc:
        logger.warning("Could not reach official URL for grant #%s (%s): %s", grant.id, grant.official_url, exc)
        return None

    current_hash = compute_content_hash(current_text)
    grant.last_checked_at = datetime.now(timezone.utc)

    # 1. Check if content hash changed
    if grant.content_hash and current_hash == grant.content_hash:
        # No modification detected
        db.add(grant)
        db.flush()
        return None

    # Content has changed on the official portal!
    logger.info("Modification detected on official page for: %s", grant.title)
    change_info: Dict[str, Any] = {
        "grant_id": grant.id,
        "title": grant.title,
        "old_hash": grant.content_hash,
        "new_hash": current_hash,
        "changes": [],
    }

    # Log content hash change
    log_update(
        db=db,
        grant_id=grant.id,
        field_name="content_hash",
        old_value=grant.content_hash,
        new_value=current_hash,
        notified=False,
    )
    change_info["changes"].append("content_hash")

    # 2. Check for deadline changes if an updated deadline was parsed
    if extracted_deadline_override is not None and extracted_deadline_override != grant.deadline:
        old_dl_str = str(grant.deadline) if grant.deadline else "None"
        new_dl_str = str(extracted_deadline_override)

        log_update(
            db=db,
            grant_id=grant.id,
            field_name="deadline",
            old_value=old_dl_str,
            new_value=new_dl_str,
            notified=True,
        )
        send_alert(
            alert_type="DEADLINE_CHANGED",
            title=grant.title,
            details=f"Official deadline updated from {old_dl_str} to {new_dl_str}! Pending human review.",
            webhook_url=webhook_url,
        )
        change_info["changes"].append(f"deadline: {old_dl_str} -> {new_dl_str}")

    # Update the content hash fingerprint (without altering other published fields automatically)
    grant.content_hash = current_hash
    db.add(grant)
    db.flush()

    return change_info


def run_monitor_cycle(
    db: Optional[Session] = None,
    reference_date: Optional[date] = None,
    page_fetcher: Optional[Callable[[str], str]] = None,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute one full monitoring cycle across all published scholarships."""
    init_db()

    def _execute(session: Session) -> Dict[str, Any]:
        logger.info("Starting scholarship monitoring cycle...")
        published_grants = session.query(Grant).filter(Grant.status == GrantStatus.PUBLISHED).all()

        modified_grants: List[Dict[str, Any]] = []
        for grant in published_grants:
            res = check_grant_updates(grant, session, page_fetcher=page_fetcher, webhook_url=webhook_url)
            if res:
                modified_grants.append(res)

        # Check closing and expiration alerts
        deadline_alerts = check_imminent_deadlines(session, reference_date=reference_date, webhook_url=webhook_url)

        session.commit()

        summary = {
            "cycle_time": datetime.now(timezone.utc).isoformat(),
            "total_published_checked": len(published_grants),
            "content_modifications_found": len(modified_grants),
            "deadline_alerts_issued": len(deadline_alerts),
            "details": {
                "modifications": modified_grants,
                "alerts": deadline_alerts,
            },
        }
        logger.info(
            "Cycle finished: Checked %d grants | %d modifications | %d deadline alerts",
            len(published_grants),
            len(modified_grants),
            len(deadline_alerts),
        )
        return summary

    if db is not None:
        return _execute(db)
    else:
        with get_db() as session:
            return _execute(session)


def start_scheduler(interval_hours: int = 24):
    """Start recurring APScheduler background job."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_monitor_cycle,
        "interval",
        hours=interval_hours,
        id="scholarship_monitor_daily",
        name="Daily Scholarship Monitor & Freshness Checker",
        replace_existing=True,
    )
    logger.info("Scheduler started: running every %d hours.", interval_hours)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


def main():
    parser = argparse.ArgumentParser(description="Scholarship Monitor Service (Task 9).")
    parser.add_argument("--now", action="store_true", help="Execute an immediate monitor check cycle and exit.")
    parser.add_argument("--schedule", action="store_true", help="Start the periodic daemon scheduler.")
    parser.add_argument("--interval", type=int, default=24, help="Hours between scheduled runs (default: 24).")
    args = parser.parse_args()

    if args.schedule:
        start_scheduler(interval_hours=args.interval)
    else:
        summary = run_monitor_cycle()
        print("\nMONITOR RUN SUMMARY:")
        print(f"- Checked: {summary['total_published_checked']} published grants")
        print(f"- Modifications: {summary['content_modifications_found']}")
        print(f"- Deadline alerts: {summary['deadline_alerts_issued']}")


if __name__ == "__main__":
    main()
