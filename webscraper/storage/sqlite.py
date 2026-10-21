from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from webscraper.models import ScrapedPage, ScrapeSession
from webscraper.storage.base import SessionRepository, SessionSummary

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    keyword     TEXT NOT NULL,
    provider    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    rank            INTEGER NOT NULL,
    url             TEXT NOT NULL,
    search_title    TEXT,
    search_snippet  TEXT,
    title           TEXT,
    description     TEXT,
    headings        TEXT,   -- JSON array
    content         TEXT,
    links           TEXT,   -- JSON array
    status_code     INTEGER,
    error           TEXT,
    fetched_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_session ON pages(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_keyword ON sessions(keyword);
"""


class SQLiteSessionRepository(SessionRepository):
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn = sqlite3.connect(":memory:") if str(path) == ":memory:" else None
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._memory_conn or sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:  # commits on success, rolls back on error
                yield conn
        finally:
            if conn is not self._memory_conn:
                conn.close()

    def save(self, session: ScrapeSession) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
            conn.execute(
                "INSERT INTO sessions (id, keyword, provider, created_at) VALUES (?, ?, ?, ?)",
                (session.id, session.keyword, session.provider, session.created_at.isoformat()),
            )
            conn.executemany(
                """INSERT INTO pages (session_id, rank, url, search_title, search_snippet, title,
                       description, headings, content, links, status_code, error, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        session.id, p.rank, p.url, p.search_title, p.search_snippet, p.title,
                        p.description, json.dumps(p.headings), p.content, json.dumps(p.links),
                        p.status_code, p.error, p.fetched_at.isoformat(),
                    )
                    for p in session.pages
                ],
            )

    def get(self, session_id: str) -> ScrapeSession | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            pages = conn.execute(
                "SELECT * FROM pages WHERE session_id = ? ORDER BY rank", (session_id,)
            ).fetchall()
        return ScrapeSession(
            id=row["id"],
            keyword=row["keyword"],
            provider=row["provider"],
            created_at=datetime.fromisoformat(row["created_at"]),
            pages=[_row_to_page(p) for p in pages],
        )

    def list(self) -> list[SessionSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT s.*, COUNT(p.id) AS page_count FROM sessions s
                   LEFT JOIN pages p ON p.session_id = s.id AND p.error IS NULL
                   GROUP BY s.id ORDER BY s.created_at DESC"""
            ).fetchall()
        return [
            SessionSummary(
                id=r["id"],
                keyword=r["keyword"],
                provider=r["provider"],
                created_at=datetime.fromisoformat(r["created_at"]),
                page_count=r["page_count"],
            )
            for r in rows
        ]

    def delete(self, session_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount > 0

    def purge_older_than(self, cutoff: datetime) -> int:
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM sessions WHERE created_at < ?", (cutoff.isoformat(),)
            ).rowcount


def _row_to_page(row: sqlite3.Row) -> ScrapedPage:
    return ScrapedPage(
        url=row["url"],
        rank=row["rank"],
        search_title=row["search_title"] or "",
        search_snippet=row["search_snippet"] or "",
        title=row["title"] or "",
        description=row["description"] or "",
        headings=json.loads(row["headings"] or "[]"),
        content=row["content"] or "",
        links=json.loads(row["links"] or "[]"),
        status_code=row["status_code"],
        error=row["error"],
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )
