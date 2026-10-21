from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from webscraper.models import ScrapeSession


@dataclass
class SessionSummary:
    id: str
    keyword: str
    provider: str
    created_at: datetime
    page_count: int  # successfully scraped pages only


class SessionRepository(ABC):
    """Persistence port. The staging and permanent stores share this interface,
    so either can be swapped (e.g. for PostgreSQL) without touching services."""

    @abstractmethod
    def save(self, session: ScrapeSession) -> None: ...

    @abstractmethod
    def get(self, session_id: str) -> ScrapeSession | None: ...

    @abstractmethod
    def list(self) -> list[SessionSummary]: ...

    @abstractmethod
    def delete(self, session_id: str) -> bool: ...

    @abstractmethod
    def purge_older_than(self, cutoff: datetime) -> int: ...
