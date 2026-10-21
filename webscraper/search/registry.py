from __future__ import annotations

import logging

from webscraper.fetching import FetchError, HttpFetcher
from webscraper.models import SearchResult
from webscraper.search.base import ProviderUnavailable, SearchProvider
from webscraper.search.brave import BraveProvider
from webscraper.search.duckduckgo import DuckDuckGoProvider
from webscraper.search.wikipedia import WikipediaProvider

log = logging.getLogger(__name__)

_PROVIDERS: dict[str, type[SearchProvider]] = {}


def register_provider(cls: type[SearchProvider]) -> type[SearchProvider]:
    _PROVIDERS[cls.name] = cls
    return cls


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


class FallbackProvider(SearchProvider):
    """Tries each provider in order and returns the first non-empty result list.

    Search engines sometimes answer automated traffic with a challenge page
    instead of results; falling back keeps a run useful when that happens.
    """

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers
        self.name = providers[0].name
        self.fetcher = providers[0].fetcher

    def search(self, keyword: str, limit: int) -> list[SearchResult]:
        errors = []
        for provider in self.providers:
            try:
                results = provider.search(keyword, limit)
            except ProviderUnavailable as exc:
                log.info("skipping %s: %s", provider.name, exc)
                continue
            except (FetchError, ValueError) as exc:  # ValueError covers malformed JSON
                errors.append(f"{provider.name}: {exc}")
                continue
            if results:
                self.name = provider.name
                return results
            log.info("%s returned no results, trying next provider", provider.name)
        if errors:
            raise FetchError("; ".join(errors))
        return []


def create_provider(spec: str, fetcher: HttpFetcher) -> SearchProvider:
    """`spec` is one provider name or a comma-separated fallback chain."""
    names = [n.strip() for n in spec.split(",") if n.strip()]
    unknown = [n for n in names if n not in _PROVIDERS]
    if not names or unknown:
        raise ValueError(
            f"Unknown search provider {', '.join(unknown) or spec!r}. "
            f"Available: {', '.join(available_providers())}"
        )
    providers = [_PROVIDERS[n](fetcher) for n in names]
    return providers[0] if len(providers) == 1 else FallbackProvider(providers)


register_provider(BraveProvider)
register_provider(DuckDuckGoProvider)
register_provider(WikipediaProvider)
