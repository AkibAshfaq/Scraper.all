"""HTTP API + static UI. Another presentation layer next to the CLI: it only
translates requests into service calls and service errors into status codes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from webscraper import __version__
from webscraper.ai import ChatError, ChatTurn
from webscraper.container import Container, build_container
from webscraper.exporters import available_formats
from webscraper.fetching import FetchError
from webscraper.models import ScrapeSession
from webscraper.search import ProviderUnavailable
from webscraper.services.chat import SUMMARY_PROMPT
from webscraper.services.sessions import SessionNotFound
from webscraper.storage import SessionSummary

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MEDIA_TYPES = {"json": "application/json", "csv": "text/csv"}


class SearchRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


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
            "chat_enabled": c.chat is not None,
            "chat_model": c.settings.chat_model,
            "summary_prompt": SUMMARY_PROMPT,
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
        if not session.documents:
            c.sessions.discard(session.id)
            raise HTTPException(
                502,
                f"Found {len(session.pages)} results, but none of the pages could be scraped "
                "(the sites blocked or rate-limited the request). Try again later.",
            )
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

    @app.post("/api/sessions/{session_id}/chat")
    def chat(session_id: str, req: ChatRequest) -> StreamingResponse:
        """Stream the reply as NDJSON events: {"type": "text"|"error"|"done", ...}."""
        if c.chat is None:
            raise HTTPException(503, "AI chat is not enabled on this server.")
        session, _ = _locate(session_id)
        turns = [ChatTurn(role=m.role, content=m.content) for m in req.messages]
        try:
            chunks = c.chat.reply(session, turns)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ChatError as exc:
            raise HTTPException(422, str(exc)) from exc

        def events() -> Iterator[str]:
            # Errors after the response has started can't change the status
            # code, so they travel in-band as an "error" event.
            try:
                for text in chunks:
                    yield json.dumps({"type": "text", "text": text}) + "\n"
            except ChatError as exc:
                yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
                return
            except Exception:
                log.exception("chat stream failed")
                yield json.dumps({"type": "error", "message": "The chat failed unexpectedly."}) + "\n"
                return
            yield json.dumps({"type": "done"}) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

    def _locate(session_id: str) -> tuple[ScrapeSession, str]:
        try:
            return c.sessions.locate(session_id)
        except SessionNotFound as exc:
            raise HTTPException(404, str(exc)) from exc

    # Mounted last so it never shadows /api routes.
    app.mount("/", RevalidatedStaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app


class RevalidatedStaticFiles(StaticFiles):
    """Static UI files with `Cache-Control: no-cache`, so browsers revalidate
    (cheap 304s via ETag) and never run a stale app.js after an upgrade."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


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
