"""Download the HTML of each page.

Waits ``delay`` seconds between requests to the same site so the site is not overloaded.
"""

from __future__ import annotations

import time
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .exceptions import FetchError
from .version import USER_AGENT

DEFAULT_DELAY = 1.0
TIMEOUT = 30.0


class Fetcher(Protocol):
    def fetch(self, url: str) -> str:
        """Return the HTML of ``url``. Raises :class:`FetchError`."""


def _get_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class HttpxFetcher:
    def __init__(
        self,
        *,
        delay: float = DEFAULT_DELAY,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.delay = delay
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
            transport=transport,
        )
        self._last_access: dict[str, float] = {}

    def _get_with_delay(self, url: str) -> httpx.Response:
        """GET ``url`` after waiting so requests to the same host are ``delay`` seconds apart."""
        origin = _get_origin(url)
        last = self._last_access.get(origin)
        if last is not None:
            wait = last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        self._last_access[origin] = time.monotonic()
        return self._client.get(url)

    def fetch(self, url: str) -> str:
        if urlsplit(url).scheme not in ("http", "https"):
            raise FetchError(f"not an http/https URL: {url}")
        try:
            response = self._get_with_delay(url)
        except httpx.TimeoutException:
            raise FetchError(f"request timed out: {url}") from None
        except httpx.HTTPError as e:
            raise FetchError(f"request failed: {url}: {e}") from None
        if not response.is_success:
            raise FetchError(f"HTTP {response.status_code}: {url}")
        content_type = response.headers.get("content-type", "")
        if content_type and not any(t in content_type for t in ("html", "xml", "text/plain")):
            raise FetchError(f"not an HTML page ({content_type}): {url}")
        return response.text

    def close(self) -> None:
        self._client.close()
