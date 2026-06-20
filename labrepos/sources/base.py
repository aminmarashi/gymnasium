"""Source-agnostic plumbing: the RepoSource protocol and a shared fetch context.

The pipeline does not care WHERE repos come from -- org listings, watchlist
people's own repos, or repos a watchlist person recently pushed to. Every source
implements ``RepoSource`` and returns ``Repo`` records already tagged with the
giant(s) it covers; the pipeline unions, dedups, signals, sorts, and reports.

``topic_filter`` lives here (not in pipeline) so both the pipeline and the
individual sources can apply the GenAI scope check without a circular import --
exactly as labpapers does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

try:  # Protocol is stdlib on 3.8+, but guard for very old typing backports.
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol, runtime_checkable

from .. import config
from ..cache import Cache
from ..http import GithubClient
from ..model import Repo


@dataclass
class FetchContext:
    """Everything a source needs for one run: the window, the selected giants,
    and the shared client / cache plus the relevant run options."""

    from_date: str
    to_date: str
    giant_keys: List[str]
    client: GithubClient
    cache: Cache
    days: int = config.DEFAULT_DAYS
    max_pages: int = 10
    require_keyword: bool = True
    include_forks: bool = False
    notable_stars: int = config.NOTABLE_STARS


@runtime_checkable
class RepoSource(Protocol):
    """A source of giant-tagged repos for a given window."""

    name: str

    def fetch(self, ctx: FetchContext) -> List[Repo]:
        ...


def topic_filter(repo: Repo, require_keyword: bool = True) -> bool:
    """Whether a repo passes the GenAI / agentic-coding topic filter.

    The PRIMARY signal is structured (``config.classify_topic``): an excluding
    GitHub topic / name phrase always wins (EXCLUDE), a decisively-GenAI GitHub
    topic keeps (KEEP), and anything inconclusive falls back to the GenAI keyword
    booster over name + description + topics + language. ``require_keyword=False``
    (the ``--no-keyword-filter`` escape hatch) disables filtering entirely.
    """

    if not require_keyword:
        return True

    verdict = config.classify_topic(repo)
    if verdict == config.EXCLUDE:
        return False
    if verdict == config.KEEP:
        return True
    # Inconclusive structure -> the GenAI keyword set is the secondary booster.
    text = " ".join((
        repo.name or "",
        repo.description or "",
        " ".join(repo.topics or []),
        repo.language or "",
    ))
    return config.has_genai_keyword(text)
