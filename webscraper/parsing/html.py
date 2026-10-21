"""Generic HTML extraction: title, description, headings, readable text, links."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urldefrag

from bs4 import BeautifulSoup

NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "nav", "footer", "header", "aside", "form")
MAX_CONTENT_CHARS = 20_000
MAX_LINKS = 200


@dataclass
class PageData:
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    content: str = ""
    links: list[str] = field(default_factory=list)


def parse_html(html: str, base_url: str) -> PageData:
    soup = BeautifulSoup(html, "html.parser")

    title = _meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    description = _meta(soup, "description") or _meta(soup, "og:description")
    links = _links(soup, base_url)

    for tag in soup(NOISE_TAGS):
        tag.decompose()

    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in root.find_all(["p", "li"])]
    text = "\n".join(p for p in paragraphs if len(p) > 30) or root.get_text(" ", strip=True)

    return PageData(
        title=title,
        description=description,
        headings=[h for h in headings if h][:50],
        content=re.sub(r"[ \t]+", " ", text)[:MAX_CONTENT_CHARS],
        links=links,
    )


def _meta(soup: BeautifulSoup, key: str) -> str:
    tag = soup.find("meta", attrs={"name": key}) or soup.find("meta", attrs={"property": key})
    return (tag.get("content") or "").strip() if tag else ""


def _links(soup: BeautifulSoup, base_url: str) -> list[str]:
    seen: dict[str, None] = {}
    for a in soup.find_all("a", href=True):
        url, _ = urldefrag(urljoin(base_url, a["href"]))
        if url.startswith(("http://", "https://")):
            seen.setdefault(url)
        if len(seen) >= MAX_LINKS:
            break
    return list(seen)
