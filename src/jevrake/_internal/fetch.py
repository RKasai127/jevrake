"""Download the HTML of each page.

Waits ``delay`` seconds between requests to the same site so the site is not overloaded.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import httpx

from .exceptions import FetchError
from .version import USER_AGENT

DEFAULT_DELAY = 1.0
TIMEOUT = 30.0


def _get_origin(url: str) -> str:
    split_url = urlsplit(url)
    return f"{split_url.scheme}://{split_url.netloc}"


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
        self._last_access_by_origin: dict[str, float] = {}

    def _get_with_delay(self, url: str) -> httpx.Response:
        """GET ``url`` after waiting so requests to the same host are ``delay`` seconds apart."""
        origin = _get_origin(url)
        last_access = self._last_access_by_origin.get(origin)
        if last_access is not None:
            wait_seconds = last_access + self.delay - time.monotonic()
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        self._last_access_by_origin[origin] = time.monotonic()
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
        is_html = any(kind in content_type for kind in ("html", "xml", "text/plain"))
        if content_type and not is_html:
            raise FetchError(f"not an HTML page ({content_type}): {url}")
        return response.text

    def close(self) -> None:
        self._client.close()
