"""Configuration module for Discovery Agents.

Loads environment variables from .env and exposes typed application settings.
"""

import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Determine project base directory and load .env file
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


class Settings(BaseModel):
    """Application settings schema and defaults."""

    # LLM Settings
    LLM_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_API_KEY"))
    LLM_MODEL: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "gemini-1.5-flash"))

    # Search Engines
    TAVILY_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("TAVILY_API_KEY"))
    SERPER_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("SERPER_API_KEY"))

    # Database
    DATABASE_URL: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///grants.db"))

    # Trusted Domains
    TRUSTED_DOMAINS_RAW: str = Field(
        default_factory=lambda: os.getenv(
            "TRUSTED_DOMAINS",
            "gov,edu,org,ac.uk,turkiyeburslari.gov.tr,chevening.org,daad.de,stipendiumhungaricum.hu,fulbrightprogram.org,campusfrance.org"
        )
    )

    # Alerts
    ALERT_WEBHOOK_URL: Optional[str] = Field(default_factory=lambda: os.getenv("ALERT_WEBHOOK_URL"))

    # Telegram (Optional / Phase 8)
    TELEGRAM_API_ID: Optional[str] = Field(default_factory=lambda: os.getenv("TELEGRAM_API_ID"))
    TELEGRAM_API_HASH: Optional[str] = Field(default_factory=lambda: os.getenv("TELEGRAM_API_HASH"))
    TELEGRAM_CHANNELS_RAW: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHANNELS", ""))

    @property
    def trusted_domains(self) -> List[str]:
        """Return list of lowercase trusted domains or TLDs."""
        if not self.TRUSTED_DOMAINS_RAW:
            return []
        return [d.strip().lower() for d in self.TRUSTED_DOMAINS_RAW.split(",") if d.strip()]

    @property
    def telegram_channels(self) -> List[str]:
        """Return list of telegram channels to monitor."""
        if not self.TELEGRAM_CHANNELS_RAW:
            return []
        return [c.strip() for c in self.TELEGRAM_CHANNELS_RAW.split(",") if c.strip()]


# Global singleton instance
settings = Settings()
