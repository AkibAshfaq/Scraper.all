"""Web API tests against an app wired with the offline fakes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import PAGE, FakeFetcher, FakeProvider
from webscraper.config import Settings
from webscraper.container import Container
from webscraper.services import ScrapeService, SessionService
from webscraper.storage import SQLiteSessionRepository
from webscraper.web import create_app


@pytest.fixture
def client(tmp_path):
    staging = SQLiteSessionRepository(tmp_path / "staging.db")
    permanent = SQLiteSessionRepository(tmp_path / "main.db")
    fetcher = FakeFetcher({"https://a.test/": PAGE})
    container = Container(
        settings=Settings(),
        scraper=ScrapeService(FakeProvider(fetcher), fetcher, staging),
        sessions=SessionService(staging, permanent, tmp_path / "out"),
    )
    return TestClient(create_app(container))


def test_search_save_flow(client):
    resp = client.post("/api/search", json={"keyword": "python", "limit": 5})
    assert resp.status_code == 200
    session = resp.json()
    assert session["store"] == "staged" and session["success_count"] == 1
    assert session["file"].endswith(".json")

    staged = client.get("/api/sessions", params={"store": "staged"}).json()
    assert [s["id"] for s in staged] == [session["id"]]

    saved = client.post(f"/api/sessions/{session['id']}/save").json()
    assert saved["store"] == "saved"
    assert client.get("/api/sessions", params={"store": "staged"}).json() == []
    assert client.get(f"/api/sessions/{session['id']}").json()["pages"][0]["title"] == "Python Guide"


def test_discard_and_missing(client):
    session = client.post("/api/search", json={"keyword": "python"}).json()
    assert client.delete(f"/api/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/sessions/{session['id']}").status_code == 404
    assert client.delete(f"/api/sessions/{session['id']}").status_code == 404


def test_export_download(client):
    session = client.post("/api/search", json={"keyword": "python"}).json()
    resp = client.get(f"/api/sessions/{session['id']}/export", params={"format": "csv"})
    assert resp.status_code == 200
    assert "Python Guide" in resp.text
    assert "attachment" in resp.headers["content-disposition"]
    assert client.get(f"/api/sessions/{session['id']}/export", params={"format": "xml"}).status_code == 400


def test_config_reports_version(client):
    from webscraper import __version__

    assert client.get("/api/config").json()["version"] == __version__


def test_validation_and_ui(client):
    assert client.post("/api/search", json={"keyword": ""}).status_code == 422
    assert client.post("/api/search", json={"keyword": "x", "limit": 999}).status_code == 422
    page = client.get("/")
    assert page.status_code == 200 and "Webscraper" in page.text
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
