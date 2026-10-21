"""Chat service + endpoint tests with a fake model (no network, no API key)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import PAGE, FakeFetcher, FakeProvider
from webscraper.ai import ChatError, ChatModel, ChatTurn
from webscraper.config import Settings
from webscraper.container import Container
from webscraper.models import ScrapedPage, ScrapeSession
from webscraper.services import ChatService, ScrapeService, SessionService
from webscraper.storage import SQLiteSessionRepository
from webscraper.web import create_app


class FakeChatModel(ChatModel):
    def __init__(self, chunks=("Hello ", "[#1]"), fail_after: int | None = None) -> None:
        self.chunks = chunks
        self.fail_after = fail_after
        self.calls: list[tuple[str, str, list[ChatTurn]]] = []

    def stream(self, instructions, context, turns):
        self.calls.append((instructions, context, turns))
        for i, chunk in enumerate(self.chunks):
            if self.fail_after is not None and i == self.fail_after:
                raise ChatError("rate limited")
            yield chunk


def make_session() -> ScrapeSession:
    return ScrapeSession(
        keyword="coral reef",
        provider="fake",
        pages=[
            ScrapedPage(url="https://a.test/", rank=1, search_title="A", search_snippet="",
                        title="Reefs", content="Coral reefs are diverse.", headings=["Intro"]),
            ScrapedPage(url="https://b.test/", rank=2, search_title="B", search_snippet="",
                        error="HTTP 429"),
        ],
    )


def test_context_includes_only_scraped_documents():
    ctx = ChatService(FakeChatModel()).build_context(make_session())
    assert ctx.document_count == 1 and not ctx.shortened
    assert 'number="1"' in ctx.text and "Coral reefs are diverse." in ctx.text
    assert "b.test" not in ctx.text


def test_context_shortens_long_documents_and_says_so():
    session = make_session()
    session.pages[0].content = "x" * 5_000
    ctx = ChatService(FakeChatModel(), max_context_chars=2_000).build_context(session)
    assert ctx.shortened
    assert "shortened to fit" in ctx.text and "[...]" in ctx.text


def test_reply_streams_from_model():
    model = FakeChatModel()
    chunks = ChatService(model).reply(make_session(), [ChatTurn("user", "Summarize")])
    assert "".join(chunks) == "Hello [#1]"
    instructions, _, turns = model.calls[0]
    assert "[#N]" in instructions and turns[-1].content == "Summarize"


def test_reply_validation():
    service = ChatService(FakeChatModel())
    with pytest.raises(ValueError):
        service.reply(make_session(), [ChatTurn("assistant", "hi")])
    empty = ScrapeSession(keyword="x", provider="fake")
    with pytest.raises(ChatError):
        service.reply(empty, [ChatTurn("user", "hi")])


@pytest.fixture
def make_client(tmp_path):
    counter = iter(range(100))

    def build(model: ChatModel | None, pages: dict | None = None) -> TestClient:
        root = tmp_path / str(next(counter))
        staging = SQLiteSessionRepository(root / "staging.db")
        permanent = SQLiteSessionRepository(root / "main.db")
        fetcher = FakeFetcher({"https://a.test/": PAGE} if pages is None else pages)
        container = Container(
            settings=Settings(),
            scraper=ScrapeService(FakeProvider(fetcher), fetcher, staging),
            sessions=SessionService(staging, permanent, root / "out"),
            chat=ChatService(model) if model else None,
        )
        return TestClient(create_app(container))

    return build


def _events(resp) -> list[dict]:
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_chat_endpoint_streams_events(make_client):
    client = make_client(FakeChatModel())
    session = client.post("/api/search", json={"keyword": "python"}).json()
    resp = client.post(f"/api/sessions/{session['id']}/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert _events(resp) == [
        {"type": "text", "text": "Hello "},
        {"type": "text", "text": "[#1]"},
        {"type": "done"},
    ]


def test_chat_error_mid_stream_is_sent_in_band(make_client):
    client = make_client(FakeChatModel(fail_after=1))
    session = client.post("/api/search", json={"keyword": "python"}).json()
    resp = client.post(f"/api/sessions/{session['id']}/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    assert _events(resp)[-1] == {"type": "error", "message": "rate limited"}


def test_chat_endpoint_errors(make_client):
    client = make_client(FakeChatModel())
    session = client.post("/api/search", json={"keyword": "python"}).json()
    url = f"/api/sessions/{session['id']}/chat"
    assert client.post(url, json={"messages": []}).status_code == 422
    assert client.post(url, json={"messages": [{"role": "assistant", "content": "x"}]}).status_code == 400
    assert client.post("/api/sessions/nope/chat", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 404
    assert make_client(None).post(url, json={"messages": [{"role": "user", "content": "x"}]}).status_code == 503


def test_failed_pages_hidden_and_all_failed_search_rejected(make_client):
    client = make_client(FakeChatModel())
    session = client.post("/api/search", json={"keyword": "python"}).json()
    assert [p["url"] for p in session["pages"]] == ["https://a.test/"]  # b.test failed
    assert client.get("/api/sessions").json()[0]["page_count"] == 1

    blocked = make_client(FakeChatModel(), pages={})
    resp = blocked.post("/api/search", json={"keyword": "python"})
    assert resp.status_code == 502 and "none of the pages could be scraped" in resp.json()["detail"]
    assert blocked.get("/api/sessions").json() == []
