"""Provider-agnostic LLM access with a strict offline fallback.

The platform is fully functional without any API key: every caller has a
deterministic path.  When a key *is* configured the same functions use it.
No credential is ever written in this file, logged, or returned to a client.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import Settings, settings

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """Raised when no provider is configured or the provider call fails."""


class LLMResponseError(RuntimeError):
    """Raised when the provider returns an unusable payload."""


_OPENAI_COMPATIBLE_DEFAULTS = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
}


def strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def resolve_provider(config: Settings = settings) -> tuple[str, str, str, str]:
    """Return (provider, api_key, model, base_url) or raise LLMUnavailable."""
    if config.offline or not config.llm_api_key:
        raise LLMUnavailable("No LLM configured (offline mode or missing key).")

    provider = config.llm_provider
    if not provider:
        key = config.llm_api_key
        if key.startswith("AIza"):
            provider = "gemini"
        elif key.startswith("sk-or-"):
            provider = "openrouter"
        elif key.startswith("gsk_"):
            provider = "groq"
        elif key.startswith("sk-"):
            provider = "openai"
        else:
            provider = "custom"

    base_url = config.llm_base_url
    model = config.llm_model
    if provider in _OPENAI_COMPATIBLE_DEFAULTS:
        default_base, default_model = _OPENAI_COMPATIBLE_DEFAULTS[provider]
        base_url = base_url or default_base
        model = model or default_model

    if provider == "gemini":
        model = model or "gemini-1.5-flash"
    elif provider == "custom":
        if not base_url:
            raise LLMUnavailable("LLM_BASE_URL is required for a custom provider.")
        if not model:
            raise LLMUnavailable("LLM_MODEL is required for a custom provider.")
    elif not model:
        raise LLMUnavailable(f"No default model for provider '{provider}'.")

    return provider, config.llm_api_key, model, base_url


def is_configured(config: Settings = settings) -> bool:
    try:
        resolve_provider(config)
    except LLMUnavailable:
        return False
    return True


def provider_label(config: Settings = settings) -> str:
    try:
        provider, _, model, _ = resolve_provider(config)
    except LLMUnavailable:
        return "deterministic"
    return f"{provider}:{model}"


def _call_gemini(
    prompt: str,
    api_key: str,
    model: str,
    json_mode: bool,
    temperature: float,
    timeout: float,
) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            url,
            params={"key": api_key},
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - provider drift
        raise LLMResponseError("Unexpected Gemini response shape.") from exc


def _call_openai_compatible(
    prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    json_mode: bool,
    temperature: float,
    timeout: float,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "ScholarshipOrchestrator/1.0",
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
    try:
        return response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - provider drift
        raise LLMResponseError("Unexpected chat-completions response shape.") from exc


def complete(
    prompt: str,
    *,
    json_mode: bool = False,
    temperature: float = 0.2,
    timeout: float | None = None,
    config: Settings = settings,
) -> str:
    """Call the configured provider and return raw text.

    Raises :class:`LLMUnavailable` when no provider/key exists so callers can
    switch to their deterministic path.
    """
    provider, api_key, model, base_url = resolve_provider(config)
    effective_timeout = timeout or config.llm_timeout
    logger.info("LLM request provider=%s model=%s json=%s", provider, model, json_mode)

    if provider == "gemini":
        raw = _call_gemini(
            prompt, api_key, model, json_mode, temperature, effective_timeout
        )
    else:
        raw = _call_openai_compatible(
            prompt, api_key, model, base_url, json_mode, temperature, effective_timeout
        )
    return strip_code_fences(raw)


def complete_json(
    prompt: str,
    *,
    temperature: float = 0.1,
    timeout: float | None = None,
    config: Settings = settings,
) -> dict[str, Any]:
    raw = complete(
        prompt,
        json_mode=True,
        temperature=temperature,
        timeout=timeout,
        config=config,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("LLM did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMResponseError("LLM JSON payload is not an object.")
    return parsed
