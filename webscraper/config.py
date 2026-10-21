"""Runtime settings, overridable through WEBSCRAPER_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"WEBSCRAPER_{name}", default)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "data")))
    output_dir: Path = field(default_factory=lambda: Path(_env("OUTPUT_DIR", "output")))
    # One provider, or a comma-separated chain tried in order until one returns results.
    search_provider: str = field(
        default_factory=lambda: _env("SEARCH_PROVIDER", "brave,duckduckgo,wikipedia")
    )
    user_agent: str = field(
        default_factory=lambda: _env(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        )
    )
    timeout: float = field(default_factory=lambda: float(_env("TIMEOUT", "15")))
    max_retries: int = field(default_factory=lambda: int(_env("MAX_RETRIES", "2")))
    max_workers: int = field(default_factory=lambda: int(_env("MAX_WORKERS", "5")))
    # Minimum seconds between requests to the same host.
    per_host_delay: float = field(default_factory=lambda: float(_env("PER_HOST_DELAY", "1.0")))
    respect_robots: bool = field(
        default_factory=lambda: _env("RESPECT_ROBOTS", "true").lower() == "true"
    )
    # AI chat (Claude). Credentials come from ANTHROPIC_API_KEY or an `ant auth login` profile.
    chat_model: str = field(default_factory=lambda: _env("CHAT_MODEL", "claude-opus-5-5"))
    chat_effort: str = field(default_factory=lambda: _env("CHAT_EFFORT", "medium"))
    # Staged (unsaved) sessions older than this are purged automatically.
    staging_ttl_hours: int = field(default_factory=lambda: int(_env("STAGING_TTL_HOURS", "24")))

    @property
    def staging_db_path(self) -> Path:
        return self.data_dir / "staging.db"

    @property
    def permanent_db_path(self) -> Path:
        return self.data_dir / "scraper.db"
