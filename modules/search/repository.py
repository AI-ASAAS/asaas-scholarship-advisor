"""TTL cache repository for external search runs and verified page extractions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from core.models import ExternalSearchCache


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_profile_cache_key(profile_payload: Dict[str, Any]) -> str:
    canonical = json.dumps(profile_payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(f"run:{canonical}".encode("utf-8")).hexdigest()
    return digest


def make_page_cache_key(url: str, content_hash: str) -> str:
    digest = hashlib.sha256(f"page:{url.strip().lower()}:{content_hash}".encode("utf-8")).hexdigest()
    return digest


class SearchCacheRepository:
    """Stateless cache repository backed by `external_search_cache`."""

    @staticmethod
    def get_cached(db: Session, query_hash: str) -> Optional[Dict[str, Any]]:
        now = _utc_now_naive()
        row = (
            db.query(ExternalSearchCache)
            .filter(
                ExternalSearchCache.query_hash == query_hash,
                ExternalSearchCache.expires_at > now,
            )
            .first()
        )
        if row is None:
            return None
        return dict(row.results_json or {})

    @staticmethod
    def set_cached(db: Session, query_hash: str, payload: Dict[str, Any], ttl_hours: int = 24) -> None:
        now = _utc_now_naive()
        expires = now + timedelta(hours=max(1, ttl_hours))
        existing = (
            db.query(ExternalSearchCache)
            .filter(ExternalSearchCache.query_hash == query_hash)
            .first()
        )
        if existing is None:
            existing = ExternalSearchCache(
                query_hash=query_hash,
                results_json=payload,
                created_at=now,
                expires_at=expires,
            )
        else:
            existing.results_json = payload
            existing.created_at = now
            existing.expires_at = expires
        db.add(existing)
        db.flush()
