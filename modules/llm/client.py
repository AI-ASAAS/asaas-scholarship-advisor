"""Single OpenAI-compatible LLM provider client over httpx (D3).

Owns timeouts, bounded retries on transport/429/5xx, ordered fallback models,
structured output validation (1 retry with error feedback), prompt-version +
token/cost logging, OpenRouter privacy defaults, and fail-closed `LLMError`.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from fastapi import Request
from pydantic import BaseModel, ValidationError

from core.config import settings
from utils.logging_redaction import redact_text

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """Raised when all models and retries fail to produce a valid response."""


def _strip_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ```) from model reply."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


def _sanitize_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if key.startswith("tvly-"):
        raise ValueError(
            "المفتاح المُدخل هو مفتاح بحث Tavily (tvly-) وليس مفتاح ذكاء اصطناعي. "
            "يرجى استخدام مفتاح LLM صحيح مع ضبط LLM_BASE_URL."
        )
    return key


def _build_response_format(schema: Type[BaseModel], mode: str) -> Dict[str, Any]:
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "schema": schema.model_json_schema(),
        },
    }


def _append_schema_instructions(
    messages: List[Dict[str, Any]],
    schema: Type[BaseModel],
) -> List[Dict[str, Any]]:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    instruction = (
        "Respond ONLY with valid JSON conforming strictly to this JSON Schema:\n"
        f"{schema_json}"
    )
    conversation = [dict(m) for m in messages]
    if conversation and conversation[0].get("role") == "system":
        if schema_json not in str(conversation[0].get("content", "")):
            conversation[0]["content"] = f"{conversation[0]['content']}\n\n{instruction}"
    else:
        conversation.insert(0, {"role": "system", "content": instruction})
    return conversation


def _build_request_body(
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: int,
    temperature: float,
    extra_body: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        **options,
        **extra_body,
    }


def _extract_message(data: Dict[str, Any]) -> Dict[str, Any]:
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise ValueError("LLM response missing choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("LLM response missing choices[0].message")
    return message


def _log_ok_call(
    model_used: str,
    prompt_version: str,
    started: float,
    data: Dict[str, Any],
) -> None:
    usage = data.get("usage") or {}
    latency_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "llm ok model=%s prompt=%s ms=%d in=%s out=%s cost=%s",
        model_used,
        prompt_version,
        latency_ms,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        usage.get("cost"),
    )


def _validation_retry_messages(
    conversation: List[Dict[str, Any]],
    raw_content: str,
    error: Exception,
) -> List[Dict[str, Any]]:
    return [
        *conversation,
        {"role": "assistant", "content": raw_content},
        {
            "role": "user",
            "content": (
                f"That reply did not match the required JSON schema:\n{error}\n"
                "Reply again with the valid JSON object only."
            ),
        },
    ]


class AsyncLLMClient:
    """Async OpenAI-compatible LLM client built on a shared `httpx.AsyncClient`."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        models: List[str],
        *,
        extra_body: Optional[Dict[str, Any]] = None,
        attempts_per_model: int = 2,
        backoff_seconds: float = 0.5,
        default_max_tokens: int = 1500,
        response_format_mode: str = "json_schema",
        configured: bool = True,
    ) -> None:
        self._http = http
        self._models = [m for m in models if m]
        self._extra_body = dict(extra_body or {})
        self._attempts = max(1, attempts_per_model)
        self._backoff = max(0.0, backoff_seconds)
        self._default_max_tokens = default_max_tokens
        self._response_format_mode = response_format_mode
        self._configured = configured

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        prompt_version: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
        **options: Any,
    ) -> Dict[str, Any]:
        """Call chat completions with bounded retries and model fallback."""
        if not self._configured or not self._models:
            raise LLMError("The AI service is not configured on the server.")

        effective_max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        for model in self._models:
            for attempt in range(self._attempts):
                body = _build_request_body(
                    model=model,
                    messages=messages,
                    max_tokens=effective_max_tokens,
                    temperature=temperature,
                    extra_body=self._extra_body,
                    options=options,
                )
                started = time.perf_counter()
                try:
                    response = await self._http.post("/chat/completions", json=body)
                except (httpx.TimeoutException, httpx.TransportError) as error:
                    logger.warning(
                        "llm transport error model=%s prompt=%s attempt=%s err=%s",
                        model,
                        prompt_version,
                        attempt,
                        type(error).__name__,
                    )
                    if attempt + 1 < self._attempts and self._backoff > 0:
                        await asyncio.sleep(self._backoff * (2**attempt))
                    continue

                if response.status_code in RETRYABLE_STATUS:
                    logger.warning(
                        "llm retryable status=%s model=%s prompt=%s attempt=%s",
                        response.status_code,
                        model,
                        prompt_version,
                        attempt,
                    )
                    if attempt + 1 < self._attempts and self._backoff > 0:
                        await asyncio.sleep(self._backoff * (2**attempt))
                    continue

                if response.status_code >= 400:
                    # Non-retryable 4xx: do not retry the same model; move to next fallback model.
                    logger.error(
                        "llm non-retryable status=%s model=%s prompt=%s detail=%s",
                        response.status_code,
                        model,
                        prompt_version,
                        redact_text(response.text[:200]),
                    )
                    break

                data = response.json()
                message = _extract_message(data)
                _log_ok_call(str(data.get("model") or model), prompt_version, started, data)
                return message

        raise LLMError("The AI service is unavailable right now. Please try again.")

    async def structured(
        self,
        messages: List[Dict[str, Any]],
        schema: Type[T],
        *,
        prompt_version: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        **options: Any,
    ) -> T:
        """Request structured JSON matching `schema` with 1 validation-feedback retry."""
        conversation = _append_schema_instructions(messages, schema)
        rf_mode = options.pop("response_format_mode", self._response_format_mode)
        response_format = options.pop("response_format", _build_response_format(schema, rf_mode))

        for _ in range(2):
            message = await self.chat(
                conversation,
                prompt_version=prompt_version,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
                **options,
            )
            content = _strip_fences(str(message.get("content") or ""))
            try:
                parsed = json.loads(content)
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as error:
                count = error.error_count() if isinstance(error, ValidationError) else 1
                logger.warning("llm output invalid prompt=%s errors=%s", prompt_version, count)
                conversation = _validation_retry_messages(conversation, content, error)

        raise LLMError("The AI answer could not be understood. Please try again.")


class SyncLLMClient:
    """Synchronous OpenAI-compatible client sharing the exact same boundary rules."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        models: Optional[List[str]] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        attempts_per_model: int = 2,
        backoff_seconds: float = 0.5,
        default_max_tokens: Optional[int] = None,
        response_format_mode: Optional[str] = None,
        http: Optional[httpx.Client] = None,
    ) -> None:
        raw_key = api_key if api_key is not None else (settings.LLM_API_KEY or "")
        self.api_key = _sanitize_key(raw_key)
        self.base_url = (base_url or settings.resolved_llm_base_url).rstrip("/")
        if models:
            self.models = [m for m in models if m]
        elif model:
            self.models = [model]
        else:
            self.models = list(settings.resolved_llm_models)
        self.model = self.models[0] if self.models else ""
        self.timeout = timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS
        self.extra_body = dict(
            extra_body if extra_body is not None else settings.resolved_llm_extra_body
        )
        self.attempts = max(1, attempts_per_model)
        self.backoff = max(0.0, backoff_seconds)
        self.default_max_tokens = (
            default_max_tokens if default_max_tokens is not None else settings.LLM_MAX_TOKENS
        )
        self.response_format_mode = response_format_mode or settings.LLM_RESPONSE_FORMAT_MODE
        self._injected_http = http

    def _clean_json_markdown(self, raw_text: str) -> str:
        """Backward-compatible helper for stripping ```json markdown fences."""
        return _strip_fences(raw_text)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        prompt_version: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
        **options: Any,
    ) -> Dict[str, Any]:
        """Call chat completions synchronously with bounded retries and model fallback."""
        if not self.api_key and self._injected_http is None:
            raise LLMError("LLM_API_KEY is not configured on the server.")
        if not self.models:
            raise LLMError("No LLM models configured.")

        effective_max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout_cfg = httpx.Timeout(self.timeout, connect=min(5.0, self.timeout))
        owns_client = self._injected_http is None
        client = (
            self._injected_http
            if self._injected_http is not None
            else httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout_cfg)
        )

        try:
            for model in self.models:
                for attempt in range(self.attempts):
                    body = _build_request_body(
                        model=model,
                        messages=messages,
                        max_tokens=effective_max_tokens,
                        temperature=temperature,
                        extra_body=self.extra_body,
                        options=options,
                    )
                    started = time.perf_counter()
                    try:
                        response = client.post("/chat/completions", json=body)
                    except (httpx.TimeoutException, httpx.TransportError) as error:
                        logger.warning(
                            "llm transport error model=%s prompt=%s attempt=%s err=%s",
                            model,
                            prompt_version,
                            attempt,
                            type(error).__name__,
                        )
                        if attempt + 1 < self.attempts and self.backoff > 0:
                            time.sleep(self.backoff * (2**attempt))
                        continue

                    if response.status_code in RETRYABLE_STATUS:
                        logger.warning(
                            "llm retryable status=%s model=%s prompt=%s attempt=%s",
                            response.status_code,
                            model,
                            prompt_version,
                            attempt,
                        )
                        if attempt + 1 < self.attempts and self.backoff > 0:
                            time.sleep(self.backoff * (2**attempt))
                        continue

                    if response.status_code >= 400:
                        logger.error(
                            "llm non-retryable status=%s model=%s prompt=%s detail=%s",
                            response.status_code,
                            model,
                            prompt_version,
                            redact_text(response.text[:200]),
                        )
                        break

                    data = response.json()
                    message = _extract_message(data)
                    _log_ok_call(str(data.get("model") or model), prompt_version, started, data)
                    return message
        finally:
            if owns_client:
                client.close()

        raise LLMError("The AI service is unavailable right now. Please try again.")

    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[T],
        prompt_version: str = "v1.0",
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        **options: Any,
    ) -> T:
        """Request structured JSON matching `schema`, with 1 retry carrying the validation error."""
        conversation = _append_schema_instructions(messages, schema)
        rf_mode = options.pop("response_format_mode", self.response_format_mode)
        response_format = options.pop("response_format", _build_response_format(schema, rf_mode))

        for _ in range(2):
            message = self.chat(
                conversation,
                prompt_version=prompt_version,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
                **options,
            )
            content = _strip_fences(str(message.get("content") or ""))
            try:
                parsed = json.loads(content)
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as error:
                count = error.error_count() if isinstance(error, ValidationError) else 1
                logger.warning("llm output invalid prompt=%s errors=%s", prompt_version, count)
                conversation = _validation_retry_messages(conversation, content, error)

        raise LLMError("The AI answer could not be understood. Please try again.")

    # Alias matching AsyncLLMClient naming
    structured = generate_structured


# Keep `LLMClient` symbol available for imports from `modules.llm`
LLMClient = SyncLLMClient


def create_async_llm_client_from_settings(
    http: httpx.AsyncClient,
) -> AsyncLLMClient:
    """Build the lifespan-managed AsyncLLMClient from settings."""
    api_key = (settings.LLM_API_KEY or "").strip()
    if api_key.startswith("tvly-"):
        api_key = ""
    return AsyncLLMClient(
        http=http,
        models=settings.resolved_llm_models,
        extra_body=settings.resolved_llm_extra_body,
        default_max_tokens=settings.LLM_MAX_TOKENS,
        response_format_mode=settings.LLM_RESPONSE_FORMAT_MODE,
        configured=bool(api_key),
    )


def create_sync_llm_client_from_settings() -> SyncLLMClient:
    """Build a synchronous LLMClient from current settings."""
    return SyncLLMClient()


def get_llm(request: Request) -> AsyncLLMClient:
    """FastAPI dependency returning the shared lifespan LLM client."""
    return request.app.state.llm
