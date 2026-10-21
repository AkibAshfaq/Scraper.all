# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- AI chat in the web UI ("Ask AI" tab, "AI summary" button): detailed summaries and
  questions answered from a search's documents by Claude, streamed, with clickable
  `[#N]` citations that open the source document.
- Git flow branching model and release process (see README).
- Single-source version in `webscraper/__init__.py`, `scripts/bump_version.py`.
- `webscraper --version`; version shown in the web UI and API docs.

### Changed
- Pages that couldn't be fetched are no longer shown in the UI, exported, or counted;
  they stay in the database. A search where no page could be scraped is discarded.
- The web server sends `Cache-Control: no-cache` for UI files so browsers pick up upgrades.

## [0.1.0] - 2026-10-22

### Added
- Keyword search with a provider fallback chain (Brave Search API, DuckDuckGo, Wikipedia).
- Concurrent page scraping with retries, per-host throttling and robots.txt support.
- Temporary (staging) SQLite database for every run; permanent database on save.
- JSON and CSV export.
- CLI: `search`, `staged`, `saved`, `save`, `discard`, `export`, `serve`.
- Web UI and JSON API for searching, reading documents, saving and downloading.
