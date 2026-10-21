from __future__ import annotations

from abc import ABC, abstractmethod

from webscraper.fetching import HttpFetcher
from webscraper.models import SearchResult


class ProviderUnavailable(Exception):
    """The provider can't run here (e.g. missing API key); a fallback chain skips it."""


class SearchProvider(ABC):
    """Turns a keyword into a ranked list of URLs.

    To add a new engine (Bing, Google CSE, a site-specific search...), subclass
    this, implement `search`, and register it in `registry.py`.
    """

    name: str = ""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher

    @abstractmethod
    def search(self, keyword: str, limit: int) -> list[SearchResult]:
        raise NotImplementedError
