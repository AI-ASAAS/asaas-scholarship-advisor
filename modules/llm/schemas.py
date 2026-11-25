"""Shared internal schemas for the LLM boundary."""

from typing import Optional
from pydantic import BaseModel


class LLMUsageRecord(BaseModel):
    """Telemetry snapshot logged per successful LLM call."""

    model: str
    prompt_version: str
    latency_ms: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost: Optional[float] = None
