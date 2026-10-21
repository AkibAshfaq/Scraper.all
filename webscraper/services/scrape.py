"""Use case: keyword -> search -> fetch pages concurrently -> parse -> stage."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from webscraper.fetching import FetchError, HttpFetcher
from webscraper.models import ScrapedPage, ScrapeSession, SearchResult
from webscraper.parsing import parse_html
from webscraper.search import SearchProvider
from webscraper.storage import SessionRepository

log = logging.getLogger(__name__)

ProgressCallback = Callable[[ScrapedPage], None]


class ScrapeService:
    def __init__(
        self,
        provider: SearchProvider,
        fetcher: HttpFetcher,
        staging: SessionRepository,
        max_workers: int = 5,
    ) -> None:
        self.provider = provider
        self.fetcher = fetcher
        self.staging = staging
        self.max_workers = max_workers

    def run(self, keyword: str, limit: int = 10, on_page: ProgressCallback | None = None) -> ScrapeSession:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword must not be empty")

        hits = self.provider.search(keyword, limit)
        log.info("%d search results for %r", len(hits), keyword)

        session = ScrapeSession(keyword=keyword, provider=self.provider.name)
        if not hits:
            return session

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for page in pool.map(self._scrape, hits):
                session.pages.append(page)
                if on_page:
                    on_page(page)

        # Every run lands in staging first; promotion to the permanent DB is explicit.
        self.staging.save(session)
        return session

    def _scrape(self, hit: SearchResult) -> ScrapedPage:
        page = ScrapedPage(
            url=hit.url, rank=hit.rank, search_title=hit.title, search_snippet=hit.snippet
        )
        try:
            resp = self.fetcher.get(hit.url)
        except FetchError as exc:
            page.error = str(exc)
            return page

        page.status_code = resp.status_code
        if "html" not in resp.content_type.lower():
            page.error = f"unsupported content type: {resp.content_type or 'unknown'}"
            return page

        data = parse_html(resp.text, resp.url)
        page.title = data.title or hit.title
        page.description = data.description
        page.headings = data.headings
        page.content = data.content
        page.links = data.links
        return page
