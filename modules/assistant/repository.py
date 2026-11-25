"""Repository layer for scoped advisor conversations and message retention (D12)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from core.models import ChatMessage, Conversation


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AssistantRepository:
    """Stateless SQLAlchemy repository managing advisor chat threads."""

    @staticmethod
    def get_or_create_conversation(db: Session, session_id: str) -> str:
        existing = (
            db.query(Conversation)
            .filter(Conversation.session_id == session_id)
            .order_by(Conversation.updated_at.desc())
            .first()
        )
        if existing is not None:
            return existing.id

        conv_id = str(uuid.uuid4())
        now = _utc_now_naive()
        db.add(
            Conversation(
                id=conv_id,
                session_id=session_id,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        return conv_id

    @staticmethod
    def append_exchange(
        db: Session,
        conversation_id: str,
        user_content: str,
        assistant_reply: str,
        attachments: List[Dict[str, Any]],
        prompt_version: str,
    ) -> None:
        now = _utc_now_naive()
        db.add(
            ChatMessage(
                conversation_id=conversation_id,
                role="user",
                content=user_content,
                attachments_json=[],
                prompt_version=None,
                created_at=now,
            )
        )
        db.add(
            ChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_reply,
                attachments_json=attachments,
                prompt_version=prompt_version,
                created_at=now,
            )
        )
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv is not None:
            conv.updated_at = now
            db.add(conv)
        db.flush()

    @staticmethod
    def list_messages(db: Session, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        conv = (
            db.query(Conversation)
            .filter(Conversation.session_id == session_id)
            .order_by(Conversation.updated_at.desc())
            .first()
        )
        if conv is None:
            return []
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.conversation_id == conv.id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
        return [
            {
                "role": r.role,
                "content": r.content,
                "attachments": list(r.attachments_json or []),
                "prompt_version": r.prompt_version,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows[-limit:]
        ]

    @staticmethod
    def purge_expired_messages(db: Session, retention_days: int = 30) -> int:
        cutoff = _utc_now_naive() - timedelta(days=max(1, retention_days))
        deleted = int(
            db.query(ChatMessage).filter(ChatMessage.created_at < cutoff).delete()
        )
        if deleted > 0:
            active_conv_ids = [r[0] for r in db.query(ChatMessage.conversation_id).distinct().all()]
            if active_conv_ids:
                db.query(Conversation).filter(Conversation.id.notin_(active_conv_ids)).delete(
                    synchronize_session=False
                )
            else:
                db.query(Conversation).filter(Conversation.updated_at < cutoff).delete(
                    synchronize_session=False
                )
        db.flush()
        return deleted
