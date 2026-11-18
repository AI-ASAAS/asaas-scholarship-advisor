"""Telegram Channel Watcher Integration (Phase 8 - Creative Extension).

Automatically monitors approved scholarship Telegram channels via Telethon,
extracts official scholarship URLs via regex, filters them against trusted domains,
deduplicates against the database, and hands each new URL directly to `ingest()`
to produce admin-ready DRAFT grants with zero manual copy-pasting.

STRICT ANTI-HALLUCINATION RULE:
- NEVER extract scholarship details (deadlines, funding, eligibility) from the Telegram post text.
- Extract ONLY the official URL from the post; all grant data MUST come from the official page via `ingest()`.
"""

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
from sqlalchemy.orm import Session

# Ensure project root is on sys.path for standalone CLI execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import settings
from core.db import get_db, init_db
from core.models import Grant
from core.repository import get_grant_by_url
from ingestion_sub_agent import ingest
from utils.url_validator import is_trusted_domain

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Regex matching HTTP/HTTPS URLs inside Arabic or English Telegram posts
URL_REGEX = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?،؛)»\"'"

# Social / chat hosts that should never be treated as official scholarship portals
NON_OFFICIAL_SOCIAL_HOSTS = {
    "t.me",
    "telegram.me",
    "telegram.dog",
    "facebook.com",
    "fb.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "wa.me",
    "chat.whatsapp.com",
    "bit.ly",
    "tinyurl.com",
}


def extract_urls_from_text(post_text: str) -> List[str]:
    """Extract and clean all HTTP/HTTPS URLs from a Telegram message body."""
    if not post_text:
        return []

    raw_matches = URL_REGEX.findall(post_text)
    cleaned: List[str] = []
    seen: Set[str] = set()

    for raw_url in raw_matches:
        url = raw_url.rstrip(TRAILING_PUNCTUATION).strip()
        if url and url not in seen:
            seen.add(url)
            cleaned.append(url)

    return cleaned


def filter_official_urls(urls: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Filter URLs to keep only trusted official scholarship domains.

    Returns:
        (trusted_urls, rejected_urls_with_reasons)
    """
    trusted: List[str] = []
    rejected: List[Tuple[str, str]] = []

    for url in urls:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if host in NON_OFFICIAL_SOCIAL_HOSTS or any(host.endswith("." + h) for h in NON_OFFICIAL_SOCIAL_HOSTS):
            rejected.append((url, f"Social/chat/shortener link '{host}' is not an official portal."))
            continue

        ok, reason = is_trusted_domain(url)
        if ok:
            trusted.append(url)
        else:
            rejected.append((url, reason))

    return trusted, rejected


def process_telegram_posts(
    posts: List[str],
    db: Optional[Session] = None,
    ingest_fn: Optional[Callable[..., Grant]] = None,
) -> Dict[str, Any]:
    """Process a batch of Telegram post texts and pass new official URLs to `ingest()`.

    Note: Post body text is used STRICTLY for URL extraction and NEVER for grant fields.
    """
    init_db()
    runner = ingest_fn or ingest

    def _run(session: Session) -> Dict[str, Any]:
        all_urls: List[str] = []
        seen_in_batch: Set[str] = set()

        for post in posts:
            for url in extract_urls_from_text(post):
                if url not in seen_in_batch:
                    seen_in_batch.add(url)
                    all_urls.append(url)

        trusted_urls, rejected_untrusted = filter_official_urls(all_urls)

        skipped_existing: List[str] = []
        drafts_created: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for url in trusted_urls:
            # Deduplicate against database
            existing = get_grant_by_url(session, url)
            if existing is not None:
                logger.info("Skipping already registered URL: %s (Grant #%s)", url, existing.id)
                skipped_existing.append(url)
                continue

            # Hand off official URL exclusively to the Ingestion Sub-Agent
            try:
                logger.info("Handing off new official URL to ingestion_sub_agent: %s", url)
                draft = runner(url, db=session)
                drafts_created.append(
                    {
                        "grant_id": draft.id,
                        "title": draft.title,
                        "official_url": draft.official_url,
                        "status": draft.status.value if hasattr(draft.status, "value") else str(draft.status),
                    }
                )
            except Exception as exc:
                logger.error("Failed to ingest URL %s: %s", url, exc)
                errors.append({"url": url, "error": str(exc)})

        session.commit()

        return {
            "posts_processed": len(posts),
            "urls_extracted": len(all_urls),
            "trusted_urls_found": len(trusted_urls),
            "drafts_created": drafts_created,
            "skipped_existing": skipped_existing,
            "skipped_untrusted": [{"url": u, "reason": r} for u, r in rejected_untrusted],
            "errors": errors,
        }

    if db is not None:
        return _run(db)
    else:
        with get_db() as session:
            return _run(session)


async def fetch_channel_posts(
    channels: Optional[List[str]] = None,
    limit: int = 20,
    session_name: str = "telegram_watcher_session",
) -> List[str]:
    """Fetch recent text posts from approved Telegram channels using Telethon."""
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise RuntimeError(
            "Telethon is not installed. Run `pip install telethon` to enable live Telegram channel reading."
        ) from exc

    api_id = settings.TELEGRAM_API_ID
    api_hash = settings.TELEGRAM_API_HASH
    target_channels = channels if channels is not None else settings.telegram_channels

    if not api_id or not api_hash:
        raise ValueError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be configured in .env to fetch live Telegram posts."
        )
    if not target_channels:
        raise ValueError(
            "No Telegram channels configured. Set TELEGRAM_CHANNELS in .env (comma-separated usernames/URLs)."
        )

    collected_posts: List[str] = []

    async with TelegramClient(session_name, int(api_id), api_hash) as client:
        for channel in target_channels:
            logger.info("Fetching latest %d posts from Telegram channel: %s", limit, channel)
            async for message in client.iter_messages(channel, limit=limit):
                if message.text:
                    collected_posts.append(message.text)

    return collected_posts


def watch_channels(limit: int = 20) -> Dict[str, Any]:
    """End-to-end live runner: fetch approved Telegram channels and ingest new official links."""
    posts = asyncio.run(fetch_channel_posts(limit=limit))
    return process_telegram_posts(posts)


def main():
    parser = argparse.ArgumentParser(description="Telegram Channel Watcher (Phase 8 Creative Task).")
    parser.add_argument("--limit", type=int, default=20, help="Number of recent posts to scan per channel.")
    args = parser.parse_args()

    report = watch_channels(limit=args.limit)
    print("\n" + "=" * 70)
    print("TELEGRAM WATCHER RUN REPORT")
    print("=" * 70)
    print(f"- Posts scanned:      {report['posts_processed']}")
    print(f"- URLs extracted:     {report['urls_extracted']}")
    print(f"- Drafts created:     {len(report['drafts_created'])}")
    print(f"- Skipped existing:   {len(report['skipped_existing'])}")
    print(f"- Skipped untrusted:  {len(report['skipped_untrusted'])}")
    print(f"- Errors:             {len(report['errors'])}")
    print("=" * 70)


if __name__ == "__main__":
    main()
