"""Pydantic contracts for in-app student notifications and admin change-review queue."""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class NotificationItemResponse(BaseModel):
    id: int
    grant_id: Optional[int] = None
    kind: str
    title: str
    body: str
    official_url: Optional[str] = None
    is_read: bool
    created_at: str


class NotificationsListResponse(BaseModel):
    unread_count: int
    high_match_alerts_enabled: bool = False
    notifications: List[NotificationItemResponse] = Field(default_factory=list)


class UnreadCountResponse(BaseModel):
    unread_count: int


class NotificationPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high_match_alerts: bool


class NotificationPreferencesResponse(BaseModel):
    high_match_alerts: bool


class GrantChangeReviewResponse(BaseModel):
    id: int
    grant_id: int
    grant_title: Optional[str] = None
    update_log_id: Optional[int] = None
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    summary_ar: str
    status: Literal["pending", "approved", "rejected"]
    reviewed_at: Optional[str] = None
    created_at: str


class GrantChangeReviewListResponse(BaseModel):
    count: int
    reviews: List[GrantChangeReviewResponse]
