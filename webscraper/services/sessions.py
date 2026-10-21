"""Use cases around stored sessions: export, promote to permanent, discard."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from webscraper.exporters import get_exporter
from webscraper.models import ScrapeSession, utcnow
from webscraper.storage import SessionRepository, SessionSummary


class SessionNotFound(LookupError):
    pass


class SessionService:
    def __init__(
        self,
        staging: SessionRepository,
        permanent: SessionRepository,
        output_dir: Path,
        staging_ttl_hours: int = 24,
    ) -> None:
        self.staging = staging
        self.permanent = permanent
        self.output_dir = output_dir
        self.staging_ttl = timedelta(hours=staging_ttl_hours)

    def export(self, session: ScrapeSession, fmt: str = "json") -> Path:
        return get_exporter(fmt).export(session, self.output_dir)

    def promote(self, session_id: str) -> ScrapeSession:
        """Copy a staged session into the permanent DB and remove it from staging."""
        session = self.staging.get(session_id)
        if session is None:
            raise SessionNotFound(f"No staged session with id {session_id!r}")
        self.permanent.save(session)
        self.staging.delete(session_id)
        return session

    def discard(self, session_id: str) -> bool:
        return self.staging.delete(session_id)

    def find(self, session_id: str) -> ScrapeSession:
        session = self.staging.get(session_id) or self.permanent.get(session_id)
        if session is None:
            raise SessionNotFound(f"No session with id {session_id!r}")
        return session

    def list_staged(self) -> list[SessionSummary]:
        return self.staging.list()

    def list_saved(self) -> list[SessionSummary]:
        return self.permanent.list()

    def purge_expired(self) -> int:
        return self.staging.purge_older_than(utcnow() - self.staging_ttl)
