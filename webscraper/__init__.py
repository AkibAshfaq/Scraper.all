"""Keyword-driven web scraper.

Layers (each depends only on the ones below it):

    cli            -> user interaction (prompts, arguments)
    services       -> use cases: scrape a keyword, promote/discard results
    search/fetch/  -> adapters for the outside world (search engines, HTTP,
    parsing/          HTML parsing)
    storage/
    exporters
    models         -> plain domain objects shared by every layer
"""

__version__ = "0.1.0"
