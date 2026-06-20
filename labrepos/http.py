"""GitHub HTTP client with a polite delay, retries, backoff, and rate-limit
handling.

Adapted from labpapers' shared HttpClient. ``GithubClient`` talks to the
GitHub REST API: it enforces a minimum interval between requests, retries on
transient failures (HTTP 429/503 and connection/timeout errors), and -- the
GitHub-specific part -- when GitHub reports a depleted rate limit (403/429 with
``X-RateLimit-Remaining: 0``) it sleeps until the reset time (capped, honouring
``Retry-After`` when present) before retrying.

Missing resources (a 404 on an org/user/repo) are non-fatal: ``get_json``
returns ``None`` so the caller can skip and degrade coverage, never abort.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional

import requests

from . import __version__

API_BASE = "https://api.github.com"


class HttpError(Exception):
    """Raised when a request ultimately fails after retries."""


class GithubClient:
    def __init__(
        self,
        token: Optional[str] = None,
        min_interval: float = 0.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        backoff_base: float = 1.5,
        max_backoff: float = 30.0,
        max_ratelimit_wait: float = 60.0,
        user_agent: Optional[str] = None,
        base_url: str = API_BASE,
    ) -> None:
        self.token = token
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.max_ratelimit_wait = max_ratelimit_wait
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        ua = user_agent or "labrepos/{v}".format(v=__version__)
        headers = {
            "User-Agent": ua,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = "Bearer {t}".format(t=token)
        self.session.headers.update(headers)
        self._last_request_at = 0.0

    # -- internals --------------------------------------------------------
    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

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

    def _maybe_ratelimited(self, resp: requests.Response) -> bool:
        """Whether a 403/429 is a depleted-rate-limit response to wait out."""

        if resp.status_code not in (403, 429):
            return False
        remaining = resp.headers.get("X-RateLimit-Remaining")
        return remaining == "0"

    def _sleep_until_reset(self, resp: requests.Response) -> None:
        retry_after = resp.headers.get("Retry-After")
        delay: Optional[float] = None
        if retry_after:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = None
        if delay is None:
            reset = resp.headers.get("X-RateLimit-Reset")
            try:
                delay = float(reset) - time.time()
            except (TypeError, ValueError):
                delay = self.max_ratelimit_wait
        delay = max(0.0, min(delay, self.max_ratelimit_wait))
        if delay > 0:
            time.sleep(delay)

    def _request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request_at = time.time()
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                self._sleep_backoff(attempt, None)
                continue

            if self._maybe_ratelimited(resp):
                if attempt >= self.max_retries:
                    raise HttpError(
                        "GitHub rate limit exhausted for {url}".format(url=url)
                    )
                self._sleep_until_reset(resp)
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
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """Fetch parsed JSON, returning ``None`` on 404.

        A missing org/user/repo is a normal, non-fatal outcome (the entry is
        skipped), exactly like labpapers' ``get_text`` returning None on 404.
        """

        resp = self._request(self._url(path), params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def iter_pages(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_pages: int = 10,
    ) -> Iterator[List[Any]]:
        """Yield one page (a JSON array) at a time, following ``Link`` rel=next.

        This is a GENERATOR so the caller can stop early: huge orgs
        (facebookresearch, microsoft, github, jetbrains) are pushed-sorted, so a
        source consuming pages lazily stops requesting more once it sees
        out-of-window data instead of pulling every page. ``per_page`` is forced
        to 100. A 404 on the first page yields nothing.
        """

        page_params: Dict[str, Any] = dict(params or {})
        page_params["per_page"] = 100
        url: Optional[str] = self._url(path)
        first = True
        pages = 0
        while url and pages < max_pages:
            resp = self._request(url, params=page_params if first else None)
            first = False
            if resp.status_code == 404:
                return
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                return
            pages += 1
            yield data
            url = _next_link(resp.headers.get("Link"))


def _next_link(link_header: Optional[str]) -> Optional[str]:
    """Extract the rel="next" URL from a GitHub ``Link`` header, if any."""

    if not link_header:
        return None
    for part in link_header.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip()
        if not (url.startswith("<") and url.endswith(">")):
            continue
        for seg in segments[1:]:
            seg = seg.strip()
            if seg in ('rel="next"', "rel=next"):
                return url[1:-1]
    return None
