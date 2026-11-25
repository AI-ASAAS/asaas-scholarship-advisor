"""Configuration module for Discovery Agents.

Loads environment variables from .env and exposes typed application settings.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Determine project base directory and load .env file
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

_PROVIDER_DEFAULT_BASE_URLS: Dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Settings(BaseModel):
    """Application settings schema and defaults."""

    # Environment mode ("development", "staging", "production")
    ENV: str = Field(default_factory=lambda: os.getenv("APP_ENV", os.getenv("ENV", "development")).strip().lower())

    # LLM Settings (D3: one OpenAI-compatible boundary, explicit provider/base_url, no key-prefix sniffing)
    LLM_PROVIDER: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openrouter").strip().lower())
    LLM_BASE_URL: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_BASE_URL"))
    LLM_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_API_KEY"))
    LLM_MODEL: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "google/gemini-2.0-flash-001"))
    LLM_MODELS_RAW: str = Field(default_factory=lambda: os.getenv("LLM_MODELS", ""))
    LLM_EXTRA_BODY_RAW: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_EXTRA_BODY"))
    LLM_TIMEOUT_SECONDS: float = Field(default_factory=lambda: _env_float("LLM_TIMEOUT_SECONDS", 30.0))
    LLM_MAX_TOKENS: int = Field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 1500))
    LLM_RESPONSE_FORMAT_MODE: str = Field(
        default_factory=lambda: os.getenv("LLM_RESPONSE_FORMAT_MODE", "json_schema").strip().lower()
    )

    # Scoped Assistant Limits & Retention (D8, D12)
    ASSISTANT_ENABLED: bool = Field(default_factory=lambda: _env_bool("ASSISTANT_ENABLED", True))
    ASSISTANT_HISTORY_LIMIT: int = Field(default_factory=lambda: _env_int("ASSISTANT_HISTORY_LIMIT", 8))
    ASSISTANT_MAX_MESSAGE_CHARS: int = Field(
        default_factory=lambda: _env_int("ASSISTANT_MAX_MESSAGE_CHARS", 1500)
    )
    ASSISTANT_MAX_STEPS: int = Field(default_factory=lambda: _env_int("ASSISTANT_MAX_STEPS", 5))
    ASSISTANT_MAX_TOKENS: int = Field(default_factory=lambda: _env_int("ASSISTANT_MAX_TOKENS", 700))
    ASSISTANT_RATE_LIMIT_PER_HOUR: int = Field(
        default_factory=lambda: _env_int("ASSISTANT_RATE_LIMIT_PER_HOUR", 60)
    )
    ASSISTANT_RETENTION_DAYS: int = Field(
        default_factory=lambda: _env_int("ASSISTANT_RETENTION_DAYS", 30)
    )

    # Documents & Strengthening Limits & Assumptions (D9, D12)
    DOCUMENTS_MAX_INPUT_CHARS: int = Field(
        default_factory=lambda: _env_int("DOCUMENTS_MAX_INPUT_CHARS", 8000)
    )
    DOCUMENTS_RATE_LIMIT_PER_HOUR: int = Field(
        default_factory=lambda: _env_int("DOCUMENTS_RATE_LIMIT_PER_HOUR", 30)
    )
    DOCUMENTS_RETENTION_DAYS: int = Field(
        default_factory=lambda: _env_int("DOCUMENTS_RETENTION_DAYS", 90)
    )
    DOCUMENTS_ASSUMED_LANGUAGE_TEST_WEEKS: int = Field(
        default_factory=lambda: _env_int("DOCUMENTS_ASSUMED_LANGUAGE_TEST_WEEKS", 6)
    )
    DOCUMENTS_MAX_TOKENS: int = Field(default_factory=lambda: _env_int("DOCUMENTS_MAX_TOKENS", 1400))

    # Personalized Application Plan Limits & Schedule Settings (Phase 6)
    PLANS_TIMEZONE: str = Field(default_factory=lambda: os.getenv("PLANS_TIMEZONE", "Asia/Aden"))
    PLANS_MILESTONE_OFFSETS_RAW: str = Field(
        default_factory=lambda: os.getenv("PLANS_MILESTONE_OFFSETS", "56,42,28,14,7,3")
    )
    PLANS_CONFLICT_WINDOW_DAYS: int = Field(
        default_factory=lambda: _env_int("PLANS_CONFLICT_WINDOW_DAYS", 7)
    )
    PLANS_SOON_DUE_DAYS: int = Field(default_factory=lambda: _env_int("PLANS_SOON_DUE_DAYS", 14))
    PLANS_RATE_LIMIT_PER_HOUR: int = Field(
        default_factory=lambda: _env_int("PLANS_RATE_LIMIT_PER_HOUR", 60)
    )
    PLANS_MAX_NOTE_CHARS: int = Field(default_factory=lambda: _env_int("PLANS_MAX_NOTE_CHARS", 2000))
    PLANS_MAX_ITEMS: int = Field(default_factory=lambda: _env_int("PLANS_MAX_ITEMS", 25))
    PLANS_SUMMARY_MAX_TOKENS: int = Field(
        default_factory=lambda: _env_int("PLANS_SUMMARY_MAX_TOKENS", 500)
    )

    # Profile-Aware External Search & Monitoring Budgets (D10, D11)
    SEARCH_MAX_QUERIES: int = Field(default_factory=lambda: _env_int("SEARCH_MAX_QUERIES", 3))
    SEARCH_MAX_PAGES: int = Field(default_factory=lambda: _env_int("SEARCH_MAX_PAGES", 5))
    SEARCH_MAX_STEPS: int = Field(default_factory=lambda: _env_int("SEARCH_MAX_STEPS", 5))
    SEARCH_WALL_CLOCK_SECONDS: float = Field(
        default_factory=lambda: _env_float("SEARCH_WALL_CLOCK_SECONDS", 30.0)
    )
    SEARCH_MAX_TOKENS_PER_RUN: int = Field(
        default_factory=lambda: _env_int("SEARCH_MAX_TOKENS_PER_RUN", 3000)
    )
    SEARCH_CACHE_TTL_HOURS: int = Field(default_factory=lambda: _env_int("SEARCH_CACHE_TTL_HOURS", 24))
    SEARCH_STUDENT_RATE_LIMIT_PER_HOUR: int = Field(
        default_factory=lambda: _env_int("SEARCH_STUDENT_RATE_LIMIT_PER_HOUR", 10)
    )
    SEARCH_GLOBAL_RATE_LIMIT_PER_HOUR: int = Field(
        default_factory=lambda: _env_int("SEARCH_GLOBAL_RATE_LIMIT_PER_HOUR", 60)
    )
    NOTIFICATIONS_DEADLINE_OFFSETS_RAW: str = Field(
        default_factory=lambda: os.getenv("NOTIFICATIONS_DEADLINE_OFFSETS", "14,7,3,1")
    )
    NOTIFICATIONS_HIGH_MATCH_THRESHOLD: float = Field(
        default_factory=lambda: _env_float("NOTIFICATIONS_HIGH_MATCH_THRESHOLD", 80.0)
    )

    # Search Engines
    TAVILY_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("TAVILY_API_KEY"))
    SERPER_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("SERPER_API_KEY"))

    # Database
    DATABASE_URL: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///grants.db"))

    # Admin Auth & Cookie Session (D4)
    ADMIN_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("ADMIN_API_KEY"))
    ALLOW_INSECURE_LOCAL_ADMIN: bool = Field(
        default_factory=lambda: _env_bool("ALLOW_INSECURE_LOCAL_ADMIN", False)
    )
    COOKIE_SECURE: bool = Field(default_factory=lambda: _env_bool("COOKIE_SECURE", False))
    ADMIN_SESSION_TTL_SECONDS: int = Field(
        default_factory=lambda: _env_int("ADMIN_SESSION_TTL_SECONDS", 28800)
    )

    # Development-only key configuration endpoint (off by default)
    ENABLE_DEV_KEYS_ENDPOINT: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_DEV_KEYS_ENDPOINT", False)
    )
    ALLOW_RUNTIME_ENV_WRITE: bool = Field(
        default_factory=lambda: _env_bool(
            "ALLOW_RUNTIME_ENV_WRITE",
            _env_bool("ENABLE_DEV_KEYS_ENDPOINT", False),
        )
    )

    # HTTP Hardening & Rate Limits
    CORS_ORIGINS_RAW: str = Field(
        default_factory=lambda: os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:8000,http://127.0.0.1:8000,"
            "http://localhost:8001,http://127.0.0.1:8001",
        )
    )
    TRUSTED_PROXIES_RAW: str = Field(default_factory=lambda: os.getenv("TRUSTED_PROXIES", ""))
    LOGIN_RATE_LIMIT: int = Field(default_factory=lambda: _env_int("LOGIN_RATE_LIMIT", 5))
    LOGIN_RATE_WINDOW_SECONDS: int = Field(
        default_factory=lambda: _env_int("LOGIN_RATE_WINDOW_SECONDS", 60)
    )
    INGEST_RATE_LIMIT: int = Field(default_factory=lambda: _env_int("INGEST_RATE_LIMIT", 20))
    SEARCH_RATE_LIMIT: int = Field(default_factory=lambda: _env_int("SEARCH_RATE_LIMIT", 20))
    AGENT_RATE_WINDOW_SECONDS: int = Field(
        default_factory=lambda: _env_int("AGENT_RATE_WINDOW_SECONDS", 3600)
    )

    # Outbound Fetch Guard
    MAX_FETCH_BYTES: int = Field(default_factory=lambda: _env_int("MAX_FETCH_BYTES", 2 * 1024 * 1024))
    MAX_REDIRECT_HOPS: int = Field(default_factory=lambda: _env_int("MAX_REDIRECT_HOPS", 3))
    ALLOWED_OUTBOUND_PORTS_RAW: str = Field(
        default_factory=lambda: os.getenv("ALLOWED_OUTBOUND_PORTS", "80,443")
    )

    # Trusted Domains
    TRUSTED_DOMAINS_RAW: str = Field(
        default_factory=lambda: os.getenv(
            "TRUSTED_DOMAINS",
            "gov,edu,org,ac.uk,turkiyeburslari.gov.tr,chevening.org,daad.de,stipendiumhungaricum.hu,fulbrightprogram.org,campusfrance.org",
        )
    )

    # Alerts
    ALERT_WEBHOOK_URL: Optional[str] = Field(default_factory=lambda: os.getenv("ALERT_WEBHOOK_URL"))

    @property
    def is_production(self) -> bool:
        return self.ENV in {"prod", "production", "staging"}

    @property
    def dev_keys_enabled(self) -> bool:
        return self.ENABLE_DEV_KEYS_ENDPOINT and not self.is_production

    @property
    def resolved_llm_base_url(self) -> str:
        """Resolve explicit OpenAI-compatible base URL from settings without key-prefix sniffing."""
        if self.LLM_BASE_URL and self.LLM_BASE_URL.strip():
            return self.LLM_BASE_URL.strip().rstrip("/")
        return _PROVIDER_DEFAULT_BASE_URLS.get(
            self.LLM_PROVIDER.strip().lower(),
            "https://openrouter.ai/api/v1",
        )

    @property
    def resolved_llm_models(self) -> List[str]:
        """Return ordered primary + fallback model list from settings."""
        raw = (self.LLM_MODELS_RAW or "").strip()
        parsed: List[str] = []
        if raw:
            if raw.startswith("["):
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, list):
                        parsed = [str(item).strip() for item in loaded if str(item).strip()]
                except json.JSONDecodeError:
                    parsed = []
            if not parsed:
                parsed = [part.strip() for part in raw.split(",") if part.strip()]
        if not parsed and self.LLM_MODEL and self.LLM_MODEL.strip():
            parsed = [self.LLM_MODEL.strip()]
        return parsed

    @property
    def resolved_llm_extra_body(self) -> Dict[str, Any]:
        """Return provider extra body (OpenRouter data_collection=deny by default)."""
        raw = self.LLM_EXTRA_BODY_RAW
        if raw is not None and raw.strip():
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    return loaded
            except json.JSONDecodeError:
                pass
        if "openrouter.ai" in self.resolved_llm_base_url.lower():
            return {"provider": {"data_collection": "deny"}}
        return {}

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS_RAW.split(",") if o.strip()]

    @property
    def trusted_proxies(self) -> Set[str]:
        return {p.strip() for p in self.TRUSTED_PROXIES_RAW.split(",") if p.strip()}

    @property
    def allowed_outbound_ports(self) -> Set[int]:
        ports: Set[int] = set()
        for raw in self.ALLOWED_OUTBOUND_PORTS_RAW.split(","):
            raw = raw.strip()
            if raw.isdigit():
                ports.add(int(raw))
        return ports or {80, 443}

    @property
    def trusted_domains(self) -> List[str]:
        """Return list of lowercase trusted domains or TLDs."""
        if not self.TRUSTED_DOMAINS_RAW:
            return []
        return [d.strip().lower() for d in self.TRUSTED_DOMAINS_RAW.split(",") if d.strip()]


# Global singleton instance
settings = Settings()
