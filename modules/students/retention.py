"""Automated privacy & data retention purge job (D12).

Enforces configured retention bounds deterministically without network or LLM calls:
- Inactive student sessions past `expires_at` (90 days inactivity) -> full atomic delete.
- Chat messages older than `ASSISTANT_RETENTION_DAYS` (30 days) + empty conversations.
- Inactive document drafts older than `DOCUMENTS_RETENTION_DAYS` (90 days).
- Read notifications older than 90 days.
- Expired external search cache rows past `expires_at` (24 hours).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from sqlalchemy.orm import Session

from core.config import settings
from core.models import (
    ChatMessage,
    Conversation,
    DocumentDraft,
    ExternalSearchCache,
    Notification,
    StudentSession,
)
from modules.students.repository import StudentRepository

logger = logging.getLogger(__name__)


def _utc_now_naive(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(timezone.utc).replace(tzinfo=None)
    return now


def run_retention_cleanup(db: Session, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """Purge expired sessions, stale messages, stale drafts, old read alerts, and expired cache."""
    cutoff_now = _utc_now_naive(now)
    msg_cutoff = cutoff_now - timedelta(days=max(1, settings.ASSISTANT_RETENTION_DAYS))
    draft_cutoff = cutoff_now - timedelta(days=max(1, settings.DOCUMENTS_RETENTION_DAYS))
    notif_cutoff = cutoff_now - timedelta(days=90)

    expired_sessions = (
        db.query(StudentSession)
        .filter(StudentSession.expires_at < cutoff_now)
        .all()
    )
    sessions_purged = 0
    for sess in expired_sessions:
        StudentRepository.delete_all_session_data(db, sess.id)
        sessions_purged += 1

    messages_purged = int(
        db.query(ChatMessage)
        .filter(ChatMessage.created_at < msg_cutoff)
        .delete(synchronize_session=False)
        or 0
    )

    # Remove conversations whose messages were all purged and that are past retention window
    active_conv_ids = db.query(ChatMessage.conversation_id).distinct()
    conversations_purged = int(
        db.query(Conversation)
        .filter(
            Conversation.updated_at < msg_cutoff,
            ~Conversation.id.in_(active_conv_ids),
        )
        .delete(synchronize_session=False)
        or 0
    )

    drafts_purged = int(
        db.query(DocumentDraft)
        .filter(DocumentDraft.updated_at < draft_cutoff)
        .delete(synchronize_session=False)
        or 0
    )

    notifications_purged = int(
        db.query(Notification)
        .filter(Notification.is_read.is_(True), Notification.created_at < notif_cutoff)
        .delete(synchronize_session=False)
        or 0
    )

    search_cache_purged = int(
        db.query(ExternalSearchCache)
        .filter(ExternalSearchCache.expires_at < cutoff_now)
        .delete(synchronize_session=False)
        or 0
    )

    db.flush()
    summary = {
        "expired_sessions": sessions_purged,
        "expired_messages": messages_purged,
        "empty_conversations": conversations_purged,
        "expired_drafts": drafts_purged,
        "expired_read_notifications": notifications_purged,
        "expired_search_cache": search_cache_purged,
    }
    logger.info("Retention cleanup completed: %s", summary)
    return summary
