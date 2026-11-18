"""LLM Extraction module implementing ASAAS AI foundation standards.

Features:
- Pydantic schema validation for structured outputs.
- Temperature = 0 for deterministic, non-hallucinatory extraction.
- Single bounded retry upon Pydantic ValidationError.
- Universal httpx client compatible with OpenAI / OpenRouter / Gemini API.
- Prompt loading with explicit version tracking from prompts/*.md.
"""

import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, TypeVar
import httpx
from pydantic import BaseModel, Field, ValidationError
from core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> Tuple[str, str]:
    """Load prompt text and version tag from prompts/<name>.md."""
    file_path = PROMPTS_DIR / f"{name}.md"
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found at {file_path}")

    content = file_path.read_text(encoding="utf-8")
    first_line, _, body = content.partition("\n")
    version = first_line.replace("version:", "").strip() if first_line.startswith("version:") else "v1.0"
    return body.strip(), version


class GrantExtractionSchema(BaseModel):
    """Pydantic schema for structured grant extraction from webpage text."""
    title: str = Field(description="Official name of the scholarship.")
    description: Optional[str] = Field(default=None, description="Concise factual description of the grant.")
    eligibility: Optional[List[str]] = Field(default=None, description="Eligibility requirements and conditions.")
    criteria: Optional[List[str]] = Field(default=None, description="Selection criteria.")
    fields_of_study: Optional[List[str]] = Field(default=None, description="Academic fields or majors eligible.")
    funding: Optional[str] = Field(default=None, description="Financial coverage and benefits.")
    required_documents: Optional[List[str]] = Field(default=None, description="Required application documents.")
    deadline: Optional[str] = Field(default=None, description="Deadline formatted as YYYY-MM-DD, or null if rolling/unknown.")
    how_to_apply: Optional[str] = Field(default=None, description="Step-by-step application instructions.")
    accepts_yemeni: Literal["yes", "no", "unclear"] = Field(
        default="unclear",
        description="Explicit eligibility for Yemeni nationals: yes, no, or unclear."
    )
    evidence: Dict[str, str] = Field(
        default_factory=dict,
        description="Dictionary mapping each extracted field name to its exact verbatim quote from the page text."
    )

    def get_parsed_deadline(self) -> Optional[date]:
        """Convert ISO deadline string to python date object if valid."""
        if not self.deadline:
            return None
        try:
            return date.fromisoformat(self.deadline.strip())
        except (ValueError, TypeError):
            return None


class LLMClient:
    """Universal OpenAI-compatible LLM client using httpx."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.LLM_API_KEY or ""
        self.model = model or settings.LLM_MODEL or "gemini-1.5-flash"
        
        # Reject misplaced Tavily search keys immediately with a clear Arabic hint
        if self.api_key.startswith("tvly-"):
            raise ValueError(
                "المفتاح المُدخل هو مفتاح بحث Tavily (tvly-) وليس مفتاح ذكاء اصطناعي. "
                "يرجى إدخال مفتاح Gemini (AIza...) أو Groq (gsk_...) أو OpenRouter (sk-or-...) أو OpenAI (sk-...)."
            )

        # Configure endpoint base_url automatically from key prefix or model
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif self.api_key.startswith("AIza"):
            # Official Google Gemini OpenAI-compatible endpoint
            self.base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
            if self.model.startswith("openrouter/"):
                self.model = "gemini-2.0-flash"
        elif self.api_key.startswith("sk-or-") or "openrouter" in (self.model or "").lower():
            # OpenRouter OpenAI-compatible endpoint
            self.base_url = "https://openrouter.ai/api/v1"
            if self.model.startswith("openrouter/"):
                self.model = self.model.removeprefix("openrouter/")
            elif "/" not in self.model:
                if self.model.startswith("gemini"):
                    self.model = f"google/{self.model}"
                elif self.model.startswith("gpt"):
                    self.model = f"openai/{self.model}"
        elif self.api_key.startswith("gsk_"):
            # Groq ultra-fast OpenAI-compatible endpoint
            self.base_url = "https://api.groq.com/openai/v1"
            if not any(x in self.model.lower() for x in ("llama", "mixtral", "qwen", "gemma")):
                self.model = "llama-3.3-70b-versatile"
        else:
            self.base_url = "https://api.openai.com/v1"

        self.timeout = timeout

    def _clean_json_markdown(self, raw_text: str) -> str:
        """Strip markdown code fences (```json ... ```) from model reply."""
        text = raw_text.strip()
        if text.startswith("```"):
            # Remove opening fence
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            # Remove closing fence
            text = re.sub(r"\n?```$", "", text)
        return text.strip()

    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[T],
        prompt_version: str = "v1.0",
        max_tokens: int = 1500,
        temperature: float = 0.0,
    ) -> T:
        """Call LLM with structured output, with 1 retry on Pydantic ValidationError."""
        if not self.api_key:
            raise ValueError(
                "LLM_API_KEY is not set in environment or .env. "
                "Please configure LLM_API_KEY to run live model extractions."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build payload with response format
        schema_dict = schema.model_json_schema()
        system_instruction = (
            "You MUST respond ONLY with valid JSON conforming strictly to this JSON Schema:\n"
            f"{json.dumps(schema_dict, ensure_ascii=False)}\n"
        )

        call_messages = list(messages)
        if not any(m.get("role") == "system" for m in call_messages):
            call_messages.insert(0, {"role": "system", "content": system_instruction})
        else:
            call_messages[0]["content"] += f"\n\n{system_instruction}"

        payload = {
            "model": self.model,
            "messages": call_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.timeout) as http:
            # First attempt
            response = http.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_reply = data["choices"][0]["message"]["content"]

            try:
                cleaned_reply = self._clean_json_markdown(raw_reply)
                parsed_json = json.loads(cleaned_reply)
                return schema.model_validate(parsed_json)
            except (json.JSONDecodeError, ValidationError) as first_err:
                logger.warning(
                    "Schema validation failed on attempt 1 (%s). Retrying once with error feedback...",
                    str(first_err)
                )

                # Retry attempt: send the error back to the model for self-correction (ASAAS standard)
                retry_messages = list(call_messages)
                retry_messages.append({"role": "assistant", "content": raw_reply})
                retry_messages.append({
                    "role": "user",
                    "content": (
                        f"Your output failed validation with error: {str(first_err)}.\n"
                        "Please correct the JSON and return only valid JSON matching the schema."
                    )
                })

                payload["messages"] = retry_messages
                retry_resp = http.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                retry_resp.raise_for_status()
                retry_data = retry_resp.json()
                retry_raw_reply = retry_data["choices"][0]["message"]["content"]

                cleaned_retry = self._clean_json_markdown(retry_raw_reply)
                final_json = json.loads(cleaned_retry)
                return schema.model_validate(final_json)


def extract_grant_from_text(
    page_text: str,
    client: Optional[LLMClient] = None,
) -> GrantExtractionSchema:
    """Extract structured scholarship data from raw webpage text."""
    prompt_text, version = load_prompt("extraction")
    llm = client or LLMClient()

    messages = [
        {"role": "system", "content": prompt_text},
        {
            "role": "user",
            "content": f"Extract all scholarship details from the following webpage text:\n\n{page_text}",
        },
    ]

    return llm.generate_structured(
        messages=messages,
        schema=GrantExtractionSchema,
        prompt_version=version,
        temperature=0.0,
    )
