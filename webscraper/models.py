"""Domain objects. No I/O here: every other layer passes these around."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SearchResult:
    """A hit returned by a search provider, before the page is fetched."""

    url: str
    title: str
    snippet: str = ""
    rank: int = 0


@dataclass
class ScrapedPage:
    """Data extracted from one fetched page."""

    url: str
    rank: int
    search_title: str
    search_snippet: str
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    content: str = ""
    links: list[str] = field(default_factory=list)
    status_code: int | None = None
    error: str | None = None
    fetched_at: datetime = field(default_factory=utcnow)

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fetched_at"] = self.fetched_at.isoformat()
        return data


@dataclass
class ScrapeSession:
    """One keyword search run and everything it produced."""

    keyword: str
    provider: str
    pages: list[ScrapedPage] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=utcnow)

    @property
    def success_count(self) -> int:
        return sum(1 for p in self.pages if p.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "keyword": self.keyword,
            "provider": self.provider,
            "created_at": self.created_at.isoformat(),
            "pages": [p.to_dict() for p in self.pages],
        }
