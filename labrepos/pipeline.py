"""Orchestration: run the configured sources, union/dedup, signal, sort.

Source-agnostic, like labpapers: ``run`` asks each ``RepoSource`` for
giant-tagged repos, unions and dedups them (a repo matched by several giants /
sources carries all tags), computes the freshness signal, sorts, and counts per
giant. The pure helpers here (``dedup_repos``, ``repos_for_giant``) are kept
network-free so they can be unit-tested directly from fixtures.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config
from .cache import Cache
from .http import GithubClient
from .model import Repo, compute_signal, merge_into, sort_repos
from .sources.base import FetchContext, RepoSource, topic_filter
from .sources.org_repos import OrgReposSource
from .sources.user_events import UserEventsSource
from .sources.user_repos import UserReposSource

__all__ = [
    "topic_filter", "dedup_repos", "repos_for_giant", "build_sources", "run",
    "Options", "Result",
]


@dataclass
class Options:
    days: int = config.DEFAULT_DAYS
    giants: List[str] = field(default_factory=lambda: list(config.GIANTS.keys()))
    out_dir: str = "reports"
    fmt: str = "both"  # md | json | both
    cache_dir: Optional[str] = "data/cache"
    token: Optional[str] = None
    max_pages: int = 10
    require_keyword: bool = True
    include_forks: bool = False
    notable_stars: int = config.NOTABLE_STARS
    include_people: bool = True
    top_per_giant: int = 15  # Markdown per-giant display cap; <=0 means no cap
    min_interval: float = 0.0
    today: Optional[_dt.date] = None  # injectable for tests / reproducibility


@dataclass
class Result:
    repos: List[Repo]
    from_date: str
    to_date: str
    giants: List[str]
    per_giant_counts: "Dict[str, int]"
    notable_stars: int = config.NOTABLE_STARS


# --------------------------------------------------------------------------
# Pure helpers (network-free, unit-testable)
# --------------------------------------------------------------------------
def dedup_repos(repos: List[Repo]) -> List[Repo]:
    """Union/dedup by ``identity_key`` (lower-cased full_name), transitively
    merging attribution lists and OR-ing the boolean flags."""

    canonical: "Dict[str, Repo]" = {}
    order: List[Repo] = []
    for repo in repos:
        key = repo.identity_key()
        existing = canonical.get(key)
        if existing is None:
            canonical[key] = repo
            order.append(repo)
        else:
            merge_into(existing, repo)
    return order


def repos_for_giant(repos: List[Repo], giant_key: str) -> List[Repo]:
    """Repos tagged with a giant, preserving the input (sorted) order."""

    return [r for r in repos if giant_key in r.giants_matched]


# --------------------------------------------------------------------------
# Live orchestration
# --------------------------------------------------------------------------
def _date_window(opts: Options) -> "tuple[str, str]":
    today = opts.today or _dt.date.today()
    frm = today - _dt.timedelta(days=opts.days)
    return frm.isoformat(), today.isoformat()


def build_sources(include_people: bool = True) -> "List[RepoSource]":
    """Instantiate the sources, in deterministic order. People sources only when
    ``include_people``."""

    sources: List[RepoSource] = [OrgReposSource()]
    if include_people:
        sources.append(UserReposSource())
        sources.append(UserEventsSource())
    return sources


def run(opts: Options, client: Optional[GithubClient] = None) -> Result:
    from_date, to_date = _date_window(opts)
    giants = config.selected_giants(opts.giants)
    giant_keys = list(giants.keys())

    client = client or GithubClient(
        token=opts.token, min_interval=opts.min_interval
    )
    cache = Cache(opts.cache_dir, enabled=bool(opts.cache_dir))

    ctx = FetchContext(
        from_date=from_date,
        to_date=to_date,
        giant_keys=giant_keys,
        client=client,
        cache=cache,
        days=opts.days,
        max_pages=opts.max_pages,
        require_keyword=opts.require_keyword,
        include_forks=opts.include_forks,
        notable_stars=opts.notable_stars,
    )

    # --- Sourcing: union of every source's giant-tagged repos ----------------
    collected: List[Repo] = []
    for source in build_sources(opts.include_people):
        try:
            collected.extend(source.fetch(ctx))
        except Exception:
            # A single source failing degrades coverage, never the whole run.
            continue

    # --- Union + dedup ------------------------------------------------------
    all_repos = dedup_repos(collected)

    # --- Signal + sort ------------------------------------------------------
    for repo in all_repos:
        compute_signal(repo, from_date, opts.notable_stars)
    all_repos = sort_repos(all_repos)

    # --- Per-giant counts ---------------------------------------------------
    report_keys = list(giant_keys)
    if opts.include_people:
        report_keys.append(config.PEOPLE_GIANT_KEY)
    per_giant_counts = {
        key: len(repos_for_giant(all_repos, key)) for key in report_keys
    }

    return Result(
        repos=all_repos,
        from_date=from_date,
        to_date=to_date,
        giants=report_keys,
        per_giant_counts=per_giant_counts,
        notable_stars=opts.notable_stars,
    )
