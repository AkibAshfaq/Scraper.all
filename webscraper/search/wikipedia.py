"""Wikipedia's official search API: reliable, but only returns Wikipedia articles."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

from webscraper.models import SearchResult
from webscraper.search.base import SearchProvider

ENDPOINT = "https://en.wikipedia.org/w/api.php"


class WikipediaProvider(SearchProvider):
    name = "wikipedia"

    def search(self, keyword: str, limit: int) -> list[SearchResult]:
        resp = self.fetcher.get(
            ENDPOINT,
            params={
                "action": "query",
                "list": "search",
                "srsearch": keyword,
                "srlimit": min(limit, 50),
                "format": "json",
            },
            check_robots=False,
        )
        items = json.loads(resp.text).get("query", {}).get("search", [])
        return [
            SearchResult(
                url="https://en.wikipedia.org/wiki/" + quote(item["title"].replace(" ", "_")),
                title=item["title"],
                snippet=html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet", ""))),
                rank=i,
            )
            for i, item in enumerate(items, 1)
        ]
