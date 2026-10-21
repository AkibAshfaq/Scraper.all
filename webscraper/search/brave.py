"""Brave Search API: real web results, needs a key (free tier available).

Get one at https://brave.com/search/api/ and set WEBSCRAPER_BRAVE_API_KEY.
"""

from __future__ import annotations

import json
import os

from webscraper.models import SearchResult
from webscraper.search.base import ProviderUnavailable, SearchProvider

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
PAGE_SIZE = 20  # API maximum per request
MAX_OFFSET = 9  # API allows page offsets 0..9


class BraveProvider(SearchProvider):
    name = "brave"

    def search(self, keyword: str, limit: int) -> list[SearchResult]:
        api_key = os.environ.get("WEBSCRAPER_BRAVE_API_KEY")
        if not api_key:
            raise ProviderUnavailable("WEBSCRAPER_BRAVE_API_KEY is not set")

        results: list[SearchResult] = []
        for offset in range(MAX_OFFSET + 1):
            resp = self.fetcher.get(
                ENDPOINT,
                params={"q": keyword, "count": min(PAGE_SIZE, limit - len(results)), "offset": offset},
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                check_robots=False,
            )
            data = json.loads(resp.text)
            items = data.get("web", {}).get("results", [])
            for item in items:
                results.append(
                    SearchResult(
                        url=item["url"],
                        title=item.get("title", ""),
                        snippet=item.get("description", ""),
                        rank=len(results) + 1,
                    )
                )
            more = data.get("query", {}).get("more_results_available", False)
            if len(results) >= limit or not items or not more:
                break
        return results[:limit]
