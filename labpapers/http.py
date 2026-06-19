"""Shared HTTP client with a polite delay, retries, and exponential backoff.

Both OpenAlex and arXiv ask consumers to be gentle. This client enforces a
minimum interval between requests and retries on transient failures (HTTP 429
and 503, plus connection/timeout errors), honoring ``Retry-After`` when given.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from . import __version__


class HttpError(Exception):
    """Raised when a request ultimately fails after retries."""


class HttpClient:
    def __init__(
        self,
        mailto: Optional[str] = None,
        min_interval: float = 0.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        backoff_base: float = 1.5,
        max_backoff: float = 30.0,
        user_agent: Optional[str] = None,
    ) -> None:
        self.mailto = mailto
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.session = requests.Session()
        ua = user_agent or "labpapers/{v}".format(v=__version__)
        if mailto:
            ua += " (mailto:{m})".format(m=mailto)
        self.session.headers.update({"User-Agent": ua})
        self._last_request_at = 0.0

    # -- internals --------------------------------------------------------
    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.time() - self._last_request_at
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)

    def _sleep_backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = min(self.backoff_base ** attempt, self.max_backoff)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except (TypeError, ValueError):
                pass
        time.sleep(delay)

    def _request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        accept: Optional[str] = None,
    ) -> requests.Response:
        headers = {}
        if accept:
            headers["Accept"] = accept
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
                self._last_request_at = time.time()
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                self._sleep_backoff(attempt, None)
                continue

            if resp.status_code in (429, 503):
                if attempt >= self.max_retries:
                    return resp
                self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                continue
            return resp

        raise HttpError(
            "request to {url} failed after {n} attempts: {exc}".format(
                url=url, n=self.max_retries + 1, exc=last_exc
            )
        )

    # -- public -----------------------------------------------------------
    def get_json(
        self, url: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        resp = self._request(url, params=params, accept="application/json")
        resp.raise_for_status()
        return resp.json()

    def get_text(
        self, url: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Fetch text, returning None on 404 or other non-fatal client errors.

        Used for the arXiv HTML fallback: a missing HTML rendering is a normal,
        non-fatal outcome (an unresolved paper is skipped, not fatal).
        """

        resp = self._request(url, params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            return None
        return resp.text
