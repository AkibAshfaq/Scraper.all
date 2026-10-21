"""Offline tests: fake fetcher/provider, real parsing, storage and services."""

from __future__ import annotations

import csv
import json
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup

from webscraper.fetching import FetchError, FetchResponse
from webscraper.models import SearchResult, utcnow
from webscraper.parsing import parse_html
from webscraper.search.base import ProviderUnavailable, SearchProvider
from webscraper.search.brave import ENDPOINT as BRAVE_ENDPOINT
from webscraper.search.brave import BraveProvider
from webscraper.search.duckduckgo import parse_results
from webscraper.search.registry import FallbackProvider, create_provider
from webscraper.services import ScrapeService, SessionService
from webscraper.services.sessions import SessionNotFound
from webscraper.storage import SQLiteSessionRepository

PAGE = """<html><head><title>Python Guide</title>
<meta name="description" content="All about Python"></head>
<body><nav>menu</nav><main><h1>Intro</h1>
<p>Python is a programming language that lets you work quickly.</p>
<a href="/docs#top">Docs</a><a href="mailto:x@y.z">mail</a></main>
<script>var x = 1;</script></body></html>"""


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.last_headers: dict = {}

    def get(self, url, params=None, headers=None, check_robots=True):
        self.last_headers = headers or {}
        if url not in self.pages:
            raise FetchError("404 Not Found")
        return FetchResponse(url=url, status_code=200, text=self.pages[url], content_type="text/html")


class FakeProvider(SearchProvider):
    name = "fake"

    def search(self, keyword, limit):
        urls = ["https://a.test/", "https://b.test/"]
        return [SearchResult(url=u, title=f"hit {i}", rank=i) for i, u in enumerate(urls[:limit], 1)]


@pytest.fixture
def stores(tmp_path):
    return SQLiteSessionRepository(tmp_path / "staging.db"), SQLiteSessionRepository(tmp_path / "main.db")


def make_services(stores, tmp_path):
    staging, permanent = stores
    fetcher = FakeFetcher({"https://a.test/": PAGE})
    scraper = ScrapeService(FakeProvider(fetcher), fetcher, staging)
    return scraper, SessionService(staging, permanent, tmp_path / "out")


def test_parse_html_extracts_fields():
    data = parse_html(PAGE, "https://a.test/page")
    assert data.title == "Python Guide"
    assert data.description == "All about Python"
    assert data.headings == ["Intro"]
    assert "programming language" in data.content
    assert "var x" not in data.content and "menu" not in data.content
    assert data.links == ["https://a.test/docs"]


def test_duckduckgo_parser_resolves_redirects_and_skips_ads():
    html = """
    <div class="result result--ad"><a class="result__a" href="https://ad.test">Ad</a></div>
    <div class="result"><a class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2F&rut=x">Python</a>
        <a class="result__snippet">Official site</a></div>"""
    hits = parse_results(BeautifulSoup(html, "html.parser"))
    assert [(h.url, h.title, h.snippet) for h in hits] == [("https://python.org/", "Python", "Official site")]


def test_brave_provider_reads_api_results(monkeypatch):
    body = json.dumps(
        {
            "query": {"more_results_available": False},
            "web": {"results": [{"url": "https://python.org/", "title": "Python", "description": "Official"}]},
        }
    )
    fetcher = FakeFetcher({BRAVE_ENDPOINT: body})
    monkeypatch.setenv("WEBSCRAPER_BRAVE_API_KEY", "test-key")
    hits = BraveProvider(fetcher).search("python", 5)
    assert [(h.url, h.title, h.snippet, h.rank) for h in hits] == [("https://python.org/", "Python", "Official", 1)]
    assert fetcher.last_headers["X-Subscription-Token"] == "test-key"


def test_brave_without_key_is_skipped_in_chain(monkeypatch):
    monkeypatch.delenv("WEBSCRAPER_BRAVE_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable):
        BraveProvider(None).search("python", 5)
    chain = FallbackProvider([BraveProvider(None), FakeProvider(None)])
    assert len(chain.search("python", 5)) == 2


def test_fallback_chain_uses_first_provider_with_results():
    class Empty(SearchProvider):
        name = "empty"

        def search(self, keyword, limit):
            return []

    class Broken(SearchProvider):
        name = "broken"

        def search(self, keyword, limit):
            raise FetchError("challenge page")

    chain = FallbackProvider([Broken(None), Empty(None), FakeProvider(None)])
    assert len(chain.search("x", 5)) == 2
    assert chain.name == "fake"
    with pytest.raises(FetchError):
        FallbackProvider([Broken(None), Empty(None)]).search("x", 5)


def test_create_provider_rejects_unknown_name():
    with pytest.raises(ValueError):
        create_provider("brave,nope", None)


def test_no_results_are_not_staged(stores, tmp_path):
    staging, permanent = stores
    scraper = ScrapeService(FakeProvider(None), FakeFetcher({}), staging)
    assert scraper.run("python", limit=0).pages == []
    assert staging.list() == []


def test_scrape_stages_session_and_records_errors(stores, tmp_path):
    scraper, sessions = make_services(stores, tmp_path)
    session = scraper.run("python")

    assert session.success_count == 1
    assert session.pages[1].error == "404 Not Found"
    assert [s.id for s in sessions.list_staged()] == [session.id]
    assert sessions.list_saved() == []


def test_promote_moves_session_to_permanent(stores, tmp_path):
    scraper, sessions = make_services(stores, tmp_path)
    session = scraper.run("python")

    sessions.promote(session.id)

    assert sessions.list_staged() == []
    saved = stores[1].get(session.id)
    assert saved.keyword == "python"
    assert saved.pages[0].headings == ["Intro"]
    with pytest.raises(SessionNotFound):
        sessions.promote(session.id)


def test_discard_and_purge(stores, tmp_path):
    scraper, sessions = make_services(stores, tmp_path)
    first = scraper.run("one")
    second = scraper.run("two")

    assert sessions.discard(first.id)
    assert stores[0].purge_older_than(utcnow() + timedelta(seconds=1)) == 1
    assert stores[0].get(second.id) is None


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_export_formats(stores, tmp_path, fmt):
    scraper, sessions = make_services(stores, tmp_path)
    session = scraper.run("python tips")
    path = sessions.export(session, fmt)

    assert path.name.startswith("python-tips_") and path.suffix == f".{fmt}"
    if fmt == "json":
        assert json.loads(path.read_text(encoding="utf-8"))["pages"][0]["title"] == "Python Guide"
    else:
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        assert rows[0]["keyword"] == "python tips" and rows[0]["title"] == "Python Guide"


def test_empty_keyword_rejected(stores, tmp_path):
    scraper, _ = make_services(stores, tmp_path)
    with pytest.raises(ValueError):
        scraper.run("   ")
