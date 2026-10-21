"""HTTP access: one place for headers, timeouts, retries and robots.txt."""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


MAX_RETRY_AFTER = 10.0  # seconds; a server asking for longer counts as a failure


class _CappedRetry(Retry):
    def get_retry_after(self, response):
        value = super().get_retry_after(response)
        return None if value is None else min(value, MAX_RETRY_AFTER)


class FetchError(Exception):
    """Raised when a page cannot be fetched (network, HTTP status, robots)."""


@dataclass
class FetchResponse:
    url: str
    status_code: int
    text: str
    content_type: str


class HttpFetcher:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 15,
        max_retries: int = 2,
        respect_robots: bool = True,
        per_host_delay: float = 1.0,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.per_host_delay = per_host_delay
        self._host_locks: dict[str, threading.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._hosts_lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        retry = _CappedRetry(
            total=max_retries,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        check_robots: bool = True,
    ) -> FetchResponse:
        # Search providers pass check_robots=False: robots.txt governs crawling the
        # result pages, not the single user-initiated query that finds them.
        if check_robots and self.respect_robots and not self._allowed(url):
            raise FetchError("blocked by robots.txt")
        return self._request("GET", url, params=params, headers=headers)

    def post(self, url: str, data: dict | None = None) -> FetchResponse:
        return self._request("POST", url, data=data)

    def _request(self, method: str, url: str, **kwargs) -> FetchResponse:
        self._throttle(urlsplit(url).netloc)
        start = time.perf_counter()
        try:
            resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
        except requests.exceptions.RetryError as exc:
            status = re.search(r"too many (\d{3}) error responses", str(exc))
            reason = f"HTTP {status.group(1)}" if status else "error responses"
            raise FetchError(f"{reason} after retries (rate limited or server error)") from exc
        except requests.exceptions.Timeout as exc:
            raise FetchError(f"timed out after {self.timeout}s") from exc
        except requests.RequestException as exc:
            raise FetchError(str(exc)) from exc
        log.debug("%s %s -> %s in %.2fs", method, url, resp.status_code, time.perf_counter() - start)
        return FetchResponse(
            url=resp.url,
            status_code=resp.status_code,
            text=resp.text,
            content_type=resp.headers.get("Content-Type", ""),
        )

    def _throttle(self, host: str) -> None:
        """Space out requests to the same host; different hosts don't wait on each other."""
        if self.per_host_delay <= 0:
            return
        with self._hosts_lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            wait = self._host_last.get(host, 0) + self.per_host_delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._host_last[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._robots_lock:
            if origin not in self._robots:
                self._robots[origin] = self._load_robots(origin)
            parser = self._robots[origin]
        # No readable robots.txt means no restrictions.
        return parser is None or parser.can_fetch(self.user_agent, url)

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        try:
            resp = self._session.get(f"{origin}/robots.txt", timeout=self.timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        return parser
