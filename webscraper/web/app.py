"""HTTP API + static UI. Another presentation layer next to the CLI: it only
translates requests into service calls and service errors into status codes."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from webscraper import __version__
from webscraper.container import Container, build_container
from webscraper.exporters import available_formats
from webscraper.fetching import FetchError
from webscraper.models import ScrapeSession
from webscraper.search import ProviderUnavailable
from webscraper.services.sessions import SessionNotFound
from webscraper.storage import SessionSummary

STATIC_DIR = Path(__file__).parent / "static"
MEDIA_TYPES = {"json": "application/json", "csv": "text/csv"}


class SearchRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)


def create_app(container: Container | None = None) -> FastAPI:
    app = FastAPI(
        title="Webscraper", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    c = container or build_container()
    c.sessions.purge_expired()

    @app.get("/api/config")
    def config() -> dict:
        return {
            "version": __version__,
            "provider": c.settings.search_provider,
            "formats": available_formats(),
            "staging_ttl_hours": c.settings.staging_ttl_hours,
        }

    # Plain `def` endpoints run in FastAPI's thread pool, so a slow scrape
    # doesn't block other requests.
    @app.post("/api/search")
    def search(req: SearchRequest) -> dict:
        try:
            session = c.scraper.run(req.keyword, limit=req.limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (FetchError, ProviderUnavailable) as exc:
            raise HTTPException(502, f"Search failed: {exc}") from exc
        if not session.pages:
            raise HTTPException(404, "No results found for that keyword.")
        path = c.sessions.export(session, "json")
        return {**_session_payload(session, "staged"), "file": str(path)}

    @app.get("/api/sessions")
    def list_sessions(store: Literal["staged", "saved"] = "staged") -> list[dict]:
        rows = c.sessions.list_staged() if store == "staged" else c.sessions.list_saved()
        return [_summary_payload(r, store) for r in rows]

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        session, store = _locate(session_id)
        return _session_payload(session, store)

    @app.post("/api/sessions/{session_id}/save")
    def save_session(session_id: str) -> dict:
        try:
            session = c.sessions.promote(session_id)
        except SessionNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return _session_payload(session, "saved")

    @app.delete("/api/sessions/{session_id}", status_code=204)
    def discard_session(session_id: str) -> None:
        if not c.sessions.discard(session_id):
            raise HTTPException(404, f"No staged session with id {session_id!r}")

    @app.get("/api/sessions/{session_id}/export")
    def export_session(session_id: str, format: str = "json") -> FileResponse:
        if format not in available_formats():
            raise HTTPException(400, f"Unknown format {format!r}")
        session, _ = _locate(session_id)
        path = c.sessions.export(session, format)
        return FileResponse(path, media_type=MEDIA_TYPES.get(format), filename=path.name)

    def _locate(session_id: str) -> tuple[ScrapeSession, str]:
        try:
            return c.sessions.locate(session_id)
        except SessionNotFound as exc:
            raise HTTPException(404, str(exc)) from exc

    # Mounted last so it never shadows /api routes.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app


def _session_payload(session: ScrapeSession, store: str) -> dict:
    return {**session.to_dict(), "store": store, "success_count": session.success_count}


def _summary_payload(row: SessionSummary, store: str) -> dict:
    return {
        "id": row.id,
        "keyword": row.keyword,
        "provider": row.provider,
        "created_at": row.created_at.isoformat(),
        "page_count": row.page_count,
        "store": store,
    }
