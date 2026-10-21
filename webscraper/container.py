"""Composition root: the only place that knows which concrete classes are used."""

from __future__ import annotations

from dataclasses import dataclass

from webscraper.ai.anthropic_model import AnthropicChatModel
from webscraper.config import Settings
from webscraper.fetching import HttpFetcher
from webscraper.search import create_provider
from webscraper.services import ChatService, ScrapeService, SessionService
from webscraper.storage import SQLiteSessionRepository


@dataclass
class Container:
    settings: Settings
    scraper: ScrapeService
    sessions: SessionService
    chat: ChatService | None = None


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    fetcher = HttpFetcher(
        user_agent=settings.user_agent,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
        respect_robots=settings.respect_robots,
        per_host_delay=settings.per_host_delay,
    )
    staging = SQLiteSessionRepository(settings.staging_db_path)
    permanent = SQLiteSessionRepository(settings.permanent_db_path)
    return Container(
        settings=settings,
        scraper=ScrapeService(
            provider=create_provider(settings.search_provider, fetcher),
            fetcher=fetcher,
            staging=staging,
            max_workers=settings.max_workers,
        ),
        sessions=SessionService(
            staging=staging,
            permanent=permanent,
            output_dir=settings.output_dir,
            staging_ttl_hours=settings.staging_ttl_hours,
        ),
        chat=ChatService(AnthropicChatModel(model=settings.chat_model, effort=settings.chat_effort)),
    )
