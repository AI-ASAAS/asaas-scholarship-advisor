"""Build the LangChain chat model used by the supervisor.

All supported providers speak the OpenAI chat-completions protocol, so a single
``ChatOpenAI`` client covers them:

* ``openai`` / ``openrouter`` / ``groq`` / ``custom`` -> their own base URL,
* ``gemini`` -> Google's OpenAI-compatible endpoint.

Credentials come exclusively from :mod:`agent_platform.llm`
(``.env`` / environment); nothing is hard-coded here.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI

from .. import llm
from ..config import Settings, settings

logger = logging.getLogger(__name__)

# Google exposes an OpenAI-compatible surface for the Gemini API.
_GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Sent to OpenRouter so the request is attributable; harmless elsewhere.
_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/scholarship-orchestrator",
    "X-Title": "Scholarship Orchestrator",
}


class AgentModelUnavailable(RuntimeError):
    """Raised when no provider is configured for the agent engine."""


def build_chat_model(config: Settings = settings) -> ChatOpenAI:
    """Return a temperature-0 tool-calling chat model for the configured provider."""
    try:
        provider, api_key, model, base_url = llm.resolve_provider(config)
    except llm.LLMUnavailable as exc:
        raise AgentModelUnavailable(str(exc)) from exc

    if provider == "gemini":
        base_url = _GEMINI_OPENAI_BASE
    if not base_url:  # pragma: no cover - resolve_provider guarantees this
        raise AgentModelUnavailable("No base URL resolved for the LLM provider.")

    headers: dict[str, Any] = (
        dict(_OPENROUTER_HEADERS) if provider == "openrouter" else {}
    )
    logger.info("Agent model provider=%s model=%s", provider, model)
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=config.llm_timeout,
        max_retries=1,
        default_headers=headers,
    )


def model_label(config: Settings = settings) -> str:
    """Human-readable provider:model label, or ``deterministic`` when unset."""
    try:
        provider, _, model, _ = llm.resolve_provider(config)
    except llm.LLMUnavailable:
        return "deterministic"
    return f"{provider}:{model}"
