"""Pydantic contracts for the scoped advisor assistant HTTP boundary."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config import settings


class AssistantMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=6000)

    @model_validator(mode="after")
    def _enforce_user_char_limit(self) -> "AssistantMessageInput":
        if self.role == "user" and len(self.content) > settings.ASSISTANT_MAX_MESSAGE_CHARS:
            raise ValueError(
                f"String should have at most {settings.ASSISTANT_MAX_MESSAGE_CHARS} characters"
            )
        return self


class AssistantAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: List[AssistantMessageInput] = Field(..., min_length=1, max_length=40)


class AssistantAskResponse(BaseModel):
    reply: str
    attachments: List[Dict[str, Any]] = Field(default_factory=list)


class AssistantStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    student_authenticated: bool = False
    has_consent: bool = False
    has_profile: bool = False
