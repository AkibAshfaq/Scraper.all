# Webscraper

Search the web for any keyword, scrape every result page, and save the data to a file.
Each run is first stored in a **temporary (staging) database**; it moves to the
**permanent database** only when you say so.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -e ".[dev]"
```

### Search provider key (recommended)

Search engines block or poison automated queries to their HTML pages, so general web results
need an official API. Get a free Brave Search API key at https://brave.com/search/api/ and set it:

```bash
setx WEBSCRAPER_BRAVE_API_KEY "your-key"      # Windows (new terminals)
export WEBSCRAPER_BRAVE_API_KEY="your-key"    # macOS/Linux
```

Without a key the scraper still runs: it tries DuckDuckGo (often answers with a bot check) and
then falls back to Wikipedia's API, which always works but only returns Wikipedia articles.

## Usage

```bash
webscraper search "machine learning" -n 10 -f json
```

1. Searches the web (Brave Search API, falling back to DuckDuckGo, then Wikipedia) and fetches up to `-n` result pages in parallel.
2. Extracts title, meta description, headings, main text and links from each page.
3. Stores the run in `data/staging.db` (temporary).
4. Writes a file to `output/` (`-f json` or `-f csv`).
5. Asks **"Save this data to the database?"** — `y` moves it to `data/scraper.db`.

Skip the prompt with `--save` or `--no-save`. Unsaved runs are purged from staging after 24 h.

| Command | Purpose |
|---|---|
| `webscraper search <keyword> [-n N] [-f json\|csv] [--save\|--no-save]` | scrape a keyword |
| `webscraper staged` | list runs in the temporary DB |
| `webscraper saved` | list runs in the permanent DB |
| `webscraper save <id>` | move a staged run to the permanent DB |
| `webscraper discard <id>` | delete a staged run |
| `webscraper export <id> [-f csv]` | re-export any run to a file |

`python -m webscraper ...` works too, without installing.

## Configuration

Environment variables (all optional):

| Variable | Default |
|---|---|
| `WEBSCRAPER_DATA_DIR` | `data` |
| `WEBSCRAPER_OUTPUT_DIR` | `output` |
| `WEBSCRAPER_BRAVE_API_KEY` | unset (Brave is skipped) |
| `WEBSCRAPER_SEARCH_PROVIDER` | `brave,duckduckgo,wikipedia` (tried in order until one returns results) |
| `WEBSCRAPER_MAX_WORKERS` | `5` |
| `WEBSCRAPER_PER_HOST_DELAY` | `1.0` (seconds between requests to the same host) |
| `WEBSCRAPER_TIMEOUT` | `15` (seconds) |
| `WEBSCRAPER_MAX_RETRIES` | `2` |
| `WEBSCRAPER_RESPECT_ROBOTS` | `true` |
| `WEBSCRAPER_STAGING_TTL_HOURS` | `24` |

## Architecture

```
cli.py                 presentation: arguments, prompts, output
container.py           composition root: wires concrete classes from Settings
services/              use cases
  scrape.py            keyword -> search -> fetch (thread pool) -> parse -> stage
  sessions.py          export, promote staging -> permanent, discard, purge
search/                SearchProvider interface, registry + fallback chain
                       (brave.py, duckduckgo.py, wikipedia.py)
fetching/http.py       HTTP client: headers, retries/backoff, per-host throttling, robots.txt
parsing/html.py        generic HTML -> title/description/headings/content/links
storage/               SessionRepository interface + SQLite implementation
exporters/             Exporter interface + JSON / CSV
models.py              domain dataclasses shared by all layers
config.py              Settings from environment
```

Dependencies point inward: services depend on the `SearchProvider`, `SessionRepository`
and `Exporter` interfaces, never on concrete adapters. Extending it:

- **New search engine** — subclass `SearchProvider`, call `register_provider(MyProvider)`,
  set `WEBSCRAPER_SEARCH_PROVIDER`.
- **New database** (PostgreSQL, MongoDB…) — implement `SessionRepository` and swap it in
  `container.py`. Staging and permanent stores can use different backends.
- **New file format** — subclass `Exporter` and add it to `_EXPORTERS`.
- **Site-specific extraction** — add a parser next to `parsing/html.py` and pick it in
  `ScrapeService._scrape` by domain.

## Tests

```bash
pytest
```

Tests run offline using fake search/fetch adapters.

Scrape responsibly: robots.txt is respected for every result page by default, and you're
responsible for following each site's terms of service. The DuckDuckGo provider reads its public
HTML results page, which often answers automated traffic with a bot check; the fallback chain
moves on when that happens. Another API (SerpAPI, Google Programmable Search…) is one
`SearchProvider` subclass away.
