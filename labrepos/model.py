"""The ``Repo`` dataclass plus freshness-signal computation and dedup merge.

The freshness signal replaces labpapers' "giant-weight": fresh repos rise to
the top sorted by ``(new_in_window, pushed_at, stars)`` descending, and an
already-notable repo (stars >= threshold) is marked -- the GitHub analogue of
the giant-author flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Repo:
    """A GitHub repository matched to a giant / watchlist person."""

    full_name: str
    owner: str = ""
    name: str = ""
    description: str = ""
    html_url: str = ""
    language: Optional[str] = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0
    created_at: Optional[str] = None  # ISO 8601 timestamp
    pushed_at: Optional[str] = None  # ISO 8601 timestamp
    topics: List[str] = field(default_factory=list)
    is_fork: bool = False
    archived: bool = False

    # attribution / provenance (union/dedup merges these)
    giants_matched: List[str] = field(default_factory=list)
    source_engines: List[str] = field(default_factory=list)
    matched_via: List[str] = field(default_factory=list)

    # computed signal fields
    new_in_window: bool = False
    active_in_window: bool = False
    is_notable: bool = False

    def identity_key(self) -> str:
        return (self.full_name or "").lower()

    def freshness_key(self) -> Tuple[int, str, int]:
        """Descending sort key: new first, then most-recently pushed, then stars."""

        return (
            1 if self.new_in_window else 0,
            self.pushed_at or "",
            self.stargazers_count,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def sort_repos(repos: List[Repo]) -> List[Repo]:
    """Sort repos by freshness signal, descending."""

    return sorted(repos, key=lambda r: r.freshness_key(), reverse=True)


def compute_signal(repo: Repo, from_date: str, notable_stars: int) -> Repo:
    """Set new/active/notable flags from created/pushed dates and the star bar.

    A repo is "new" when its ``created_at`` is in window; otherwise "active"
    when its ``pushed_at`` is in window. (GitHub guarantees
    ``pushed_at >= created_at``, so a new repo is necessarily active too; we
    keep them as distinct, non-exclusive flags and label "new" preferentially.)
    """

    created = repo.created_at or ""
    pushed = repo.pushed_at or ""
    repo.new_in_window = bool(created) and created >= from_date
    repo.active_in_window = bool(pushed) and pushed >= from_date
    repo.is_notable = repo.stargazers_count >= notable_stars
    return repo


def merge_into(into: Repo, other: Repo) -> None:
    """Union attribution lists and OR the boolean flags (mirrors labpapers)."""

    for g in other.giants_matched:
        if g not in into.giants_matched:
            into.giants_matched.append(g)
    for eng in other.source_engines:
        if eng not in into.source_engines:
            into.source_engines.append(eng)
    for via in other.matched_via:
        if via not in into.matched_via:
            into.matched_via.append(via)
    into.new_in_window = into.new_in_window or other.new_in_window
    into.active_in_window = into.active_in_window or other.active_in_window
    into.is_notable = into.is_notable or other.is_notable
    # Prefer non-empty descriptive fields if the survivor lacks them.
    if not into.description and other.description:
        into.description = other.description
    if into.language is None and other.language is not None:
        into.language = other.language
    if not into.topics and other.topics:
        into.topics = list(other.topics)
    into.stargazers_count = max(into.stargazers_count, other.stargazers_count)
    into.forks_count = max(into.forks_count, other.forks_count)


def parse_repo(
    obj: Dict[str, Any],
    matched_giant: Optional[str] = None,
    source_engine: Optional[str] = None,
    matched_via: Optional[str] = None,
) -> Repo:
    """Build a ``Repo`` from a GitHub repo JSON object, tolerant of missing keys."""

    obj = obj or {}
    owner_obj = obj.get("owner") or {}
    owner = owner_obj.get("login") or ""
    full_name = obj.get("full_name") or ""
    name = obj.get("name") or ""
    if not name and full_name and "/" in full_name:
        name = full_name.split("/", 1)[1]
    if not owner and full_name and "/" in full_name:
        owner = full_name.split("/", 1)[0]
    topics = obj.get("topics") or []
    if not isinstance(topics, list):
        topics = []

    repo = Repo(
        full_name=full_name,
        owner=owner,
        name=name,
        description=obj.get("description") or "",
        html_url=obj.get("html_url") or "",
        language=obj.get("language"),
        stargazers_count=int(obj.get("stargazers_count") or 0),
        forks_count=int(obj.get("forks_count") or 0),
        open_issues_count=int(obj.get("open_issues_count") or 0),
        created_at=obj.get("created_at"),
        pushed_at=obj.get("pushed_at"),
        topics=[str(t) for t in topics],
        is_fork=bool(obj.get("fork")),
        archived=bool(obj.get("archived")),
    )
    if matched_giant:
        repo.giants_matched = [matched_giant]
    if source_engine:
        repo.source_engines = [source_engine]
    if matched_via:
        repo.matched_via = [matched_via]
    return repo
