"""Repository layer for student saved document drafts (D9, D12)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from core.models import DocumentDraft, Grant


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_record(row: DocumentDraft, grant_title: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "grant_id": row.grant_id,
        "grant_title": grant_title,
        "doc_type": row.doc_type,
        "language": row.language,
        "facts_ledger": list(row.facts_ledger_json or []),
        "draft_text": row.draft_text,
        "flagged_claims": list(row.flagged_claims_json or []),
        "prompt_version": row.prompt_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class DocumentsRepository:
    """Stateless SQLAlchemy repository for saved application document drafts."""

    @staticmethod
    def create_draft(
        db: Session,
        *,
        session_id: str,
        grant_id: Optional[int],
        doc_type: str,
        language: str,
        facts_ledger: List[Dict[str, Any]],
        draft_text: str,
        flagged_claims: List[Dict[str, Any]],
        prompt_version: Optional[str],
    ) -> Dict[str, Any]:
        now = _utc_now_naive()
        row = DocumentDraft(
            session_id=session_id,
            grant_id=grant_id,
            doc_type=doc_type,
            language=language,
            facts_ledger_json=facts_ledger,
            draft_text=draft_text,
            flagged_claims_json=flagged_claims,
            prompt_version=prompt_version,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        grant_title = None
        if grant_id:
            g = db.query(Grant).filter(Grant.id == grant_id).first()
            grant_title = g.title if g else None
        return _to_record(row, grant_title=grant_title)

    @staticmethod
    def list_drafts(db: Session, session_id: str) -> List[Dict[str, Any]]:
        rows = (
            db.query(DocumentDraft)
            .filter(DocumentDraft.session_id == session_id)
            .order_by(DocumentDraft.updated_at.desc(), DocumentDraft.id.desc())
            .all()
        )
        grant_ids = {r.grant_id for r in rows if r.grant_id is not None}
        titles: Dict[int, str] = {}
        if grant_ids:
            for g in db.query(Grant).filter(Grant.id.in_(grant_ids)).all():
                titles[g.id] = g.title
        return [_to_record(r, grant_title=titles.get(r.grant_id) if r.grant_id else None) for r in rows]

    @staticmethod
    def get_draft(db: Session, session_id: str, draft_id: int) -> Optional[Dict[str, Any]]:
        row = (
            db.query(DocumentDraft)
            .filter(DocumentDraft.id == draft_id, DocumentDraft.session_id == session_id)
            .first()
        )
        if row is None:
            return None
        grant_title = None
        if row.grant_id:
            g = db.query(Grant).filter(Grant.id == row.grant_id).first()
            grant_title = g.title if g else None
        return _to_record(row, grant_title=grant_title)

    @staticmethod
    def update_draft(
        db: Session,
        *,
        session_id: str,
        draft_id: int,
        draft_text: Optional[str] = None,
        flagged_claims: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        row = (
            db.query(DocumentDraft)
            .filter(DocumentDraft.id == draft_id, DocumentDraft.session_id == session_id)
            .first()
        )
        if row is None:
            return None
        if draft_text is not None:
            row.draft_text = draft_text
        if flagged_claims is not None:
            row.flagged_claims_json = flagged_claims
        row.updated_at = _utc_now_naive()
        db.add(row)
        db.flush()
        grant_title = None
        if row.grant_id:
            g = db.query(Grant).filter(Grant.id == row.grant_id).first()
            grant_title = g.title if g else None
        return _to_record(row, grant_title=grant_title)

    @staticmethod
    def delete_draft(db: Session, session_id: str, draft_id: int) -> bool:
        deleted = int(
            db.query(DocumentDraft)
            .filter(DocumentDraft.id == draft_id, DocumentDraft.session_id == session_id)
            .delete()
        )
        db.flush()
        return deleted > 0

    @staticmethod
    def purge_expired_drafts(db: Session, retention_days: int = 90) -> int:
        cutoff = _utc_now_naive() - timedelta(days=max(1, retention_days))
        deleted = int(db.query(DocumentDraft).filter(DocumentDraft.updated_at < cutoff).delete())
        db.flush()
        return deleted
