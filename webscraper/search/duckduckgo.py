"""DuckDuckGo's HTML endpoint: no API key, paginated via a POST form."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup

from webscraper.models import SearchResult
from webscraper.search.base import SearchProvider

ENDPOINT = "https://html.duckduckgo.com/html/"
MAX_PAGES = 5


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def search(self, keyword: str, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        form: dict[str, str] = {"q": keyword}

        for _ in range(MAX_PAGES):
            html = self.fetcher.post(ENDPOINT, data=form).text
            soup = BeautifulSoup(html, "html.parser")
            for hit in parse_results(soup):
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                hit.rank = len(results) + 1
                results.append(hit)
                if len(results) >= limit:
                    return results
            form = _next_page_form(soup)
            if not form:
                break
        return results


def parse_results(soup: BeautifulSoup) -> list[SearchResult]:
    hits = []
    for block in soup.select("div.result"):
        if "result--ad" in block.get("class", []):
            continue
        link = block.select_one("a.result__a")
        if not link or not link.get("href"):
            continue
        url = _resolve_redirect(link["href"])
        if not url.startswith(("http://", "https://")):
            continue
        snippet = block.select_one(".result__snippet")
        hits.append(
            SearchResult(
                url=url,
                title=link.get_text(" ", strip=True),
                snippet=snippet.get_text(" ", strip=True) if snippet else "",
            )
        )
    return hits


def _resolve_redirect(href: str) -> str:
    # Links look like //duckduckgo.com/l/?uddg=<encoded target>&rut=...
    parts = urlsplit(href)
    if parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


def _next_page_form(soup: BeautifulSoup) -> dict[str, str]:
    for form in soup.select("div.nav-link form"):
        button = form.select_one("input[type=submit]")
        if button and "next" in (button.get("value") or "").lower():
            return {
                i["name"]: i.get("value", "")
                for i in form.select("input[name]")
                if i.get("type") != "submit"
            }
    return {}
