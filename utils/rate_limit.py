"""In-memory sliding-window rate limiter and trusted-proxy client IP extraction."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Iterable, Optional

from fastapi import HTTPException, Request, status


def get_client_ip(request: Request, trusted_proxies: Optional[Iterable[str]] = None) -> str:
    """Resolve client IP without blindly trusting X-Forwarded-For."""
    peer_ip = request.client.host if request.client else "unknown"
    trusted = set(trusted_proxies or ())
    if peer_ip in trusted:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            hops = [part.strip() for part in forwarded_for.split(",") if part.strip()]
            # Walk from rightmost hop outward, returning the first non-trusted proxy IP.
            for hop in reversed(hops):
                if hop not in trusted:
                    return hop
            if hops:
                return hops[0]
    return peer_ip


class RateLimiter:
    """Thread-safe in-memory sliding-window rate limiter."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = max(1, int(limit))
        self._window = max(1.0, float(window_seconds))
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: Optional[int] = None, window_seconds: Optional[float] = None) -> None:
        """Record a hit for ``key`` or raise HTTP 429 with Retry-After when exceeded."""
        eff_limit = max(1, int(limit if limit is not None else self._limit))
        eff_window = max(1.0, float(window_seconds if window_seconds is not None else self._window))
        now = time.monotonic()

        with self._lock:
            hits = self._hits[key]
            while hits and (now - hits[0]) > eff_window:
                hits.popleft()
            if len(hits) >= eff_limit:
                retry_after = max(1, int(eff_window - (now - hits[0])) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "message": "تم تجاوز الحد المسموح من المحاولات؛ انتظر قليلاً ثم أعد المحاولة.",
                        "code": "RATE_LIMITED",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
            if len(self._hits) > 4096:
                stale_keys = [k for k, bucket in self._hits.items() if not bucket]
                for k in stale_keys:
                    del self._hits[k]

    def reset(self) -> None:
        """Clear recorded hits (primarily for isolated tests)."""
        with self._lock:
            self._hits.clear()
