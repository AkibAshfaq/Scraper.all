# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Git flow branching model and release process (see README).
- Single-source version in `webscraper/__init__.py`, `scripts/bump_version.py`.
- `webscraper --version`; version shown in the web UI and API docs.

## [0.1.0] - 2026-10-22

### Added
- Keyword search with a provider fallback chain (Brave Search API, DuckDuckGo, Wikipedia).
- Concurrent page scraping with retries, per-host throttling and robots.txt support.
- Temporary (staging) SQLite database for every run; permanent database on save.
- JSON and CSV export.
- CLI: `search`, `staged`, `saved`, `save`, `discard`, `export`, `serve`.
- Web UI and JSON API for searching, reading documents, saving and downloading.
