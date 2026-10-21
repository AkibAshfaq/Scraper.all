from __future__ import annotations

import csv
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from webscraper.models import ScrapeSession


class Exporter(ABC):
    """Writes a session to a file. Add a format by subclassing and registering."""

    extension: str = ""

    def export(self, session: ScrapeSession, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", session.keyword.lower()).strip("-") or "search"
        stamp = session.created_at.strftime("%Y%m%d-%H%M%S")
        path = output_dir / f"{slug}_{stamp}_{session.id}.{self.extension}"
        self.write(session, path)
        return path

    @abstractmethod
    def write(self, session: ScrapeSession, path: Path) -> None: ...


class JsonExporter(Exporter):
    extension = "json"

    def write(self, session: ScrapeSession, path: Path) -> None:
        path.write_text(json.dumps(session.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


class CsvExporter(Exporter):
    extension = "csv"
    columns = (
        "rank", "url", "title", "description", "search_snippet",
        "headings", "content", "status_code", "error", "fetched_at",
    )

    def write(self, session: ScrapeSession, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=("keyword", *self.columns))
            writer.writeheader()
            for page in session.documents:
                row = page.to_dict()
                row["headings"] = " | ".join(page.headings)
                writer.writerow({"keyword": session.keyword, **{c: row[c] for c in self.columns}})


_EXPORTERS: dict[str, type[Exporter]] = {"json": JsonExporter, "csv": CsvExporter}


def available_formats() -> list[str]:
    return sorted(_EXPORTERS)


def get_exporter(fmt: str) -> Exporter:
    try:
        return _EXPORTERS[fmt.lower()]()
    except KeyError:
        raise ValueError(f"Unknown format {fmt!r}. Available: {', '.join(available_formats())}") from None
