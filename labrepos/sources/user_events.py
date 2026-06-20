"""Watchlist source: repos a tracked person recently CONTRIBUTED to.

The "contributing to" signal -- repos a giant person pushes to but does not
necessarily own. For each watchlist username we read the public Events API
(``/users/{user}/events/public``), collect distinct repo full_names from
``PushEvent`` / ``CreateEvent`` / ``PullRequestEvent`` whose event timestamp is
in window, fetch each repo's metadata, then apply the SAME filters as the other
sources (drop forks, keep in-window, topic filter).

Best-effort throughout: a 404 (unknown user, missing repo) returns None and is
skipped; each per-user pass is wrapped in try/except.
"""

from __future__ import annotations

from typing import List

from .. import config, watchlist as watchlist_config
from ..model import Repo, parse_repo
from .base import FetchContext, topic_filter

_CONTRIB_EVENTS = {"PushEvent", "CreateEvent", "PullRequestEvent"}


class UserEventsSource:
    name = "user-events"

    def fetch(self, ctx: FetchContext) -> List[Repo]:
        out: List[Repo] = []
        for person in watchlist_config.WATCHLIST_PEOPLE:
            user = person.get("username")
            if not user:
                continue
            try:
                out.extend(self._fetch_user(ctx, user))
            except Exception:
                continue
        return out

    def _fetch_user(self, ctx: FetchContext, user: str) -> List[Repo]:
        events = ctx.client.get_json(
            "/users/{user}/events/public".format(user=user)
        )
        if not events:
            return []

        full_names: List[str] = []
        seen = set()
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") not in _CONTRIB_EVENTS:
                continue
            created = ev.get("created_at") or ""
            if not created or created < ctx.from_date:
                continue
            repo_obj = ev.get("repo") or {}
            full_name = repo_obj.get("name")  # Events API: "owner/repo"
            if full_name and full_name not in seen:
                seen.add(full_name)
                full_names.append(full_name)

        out: List[Repo] = []
        for full_name in full_names:
            obj = self._get_repo(ctx, full_name)
            if not obj:
                continue
            repo = parse_repo(obj)
            if repo.is_fork and not ctx.include_forks:
                continue
            pushed = repo.pushed_at or ""
            if not pushed or pushed < ctx.from_date:
                continue
            repo.giants_matched = [config.PEOPLE_GIANT_KEY]
            repo.source_engines = [self.name]
            repo.matched_via = ["user-event:{user}".format(user=user)]
            owner_giant = config.giant_for_org(repo.owner)
            if owner_giant and owner_giant not in repo.giants_matched:
                repo.giants_matched.append(owner_giant)
            if topic_filter(repo, ctx.require_keyword):
                out.append(repo)
        return out

    def _get_repo(self, ctx: FetchContext, full_name: str):
        # Fetch per-repo metadata FRESH each run -- deliberately uncached.
        # Dynamic fields (pushed_at, stars, topics, description) change between
        # runs; a stale cached pushed_at would drop a fresh in-window PushEvent
        # contribution. Correctness here outweighs the saved request.
        return ctx.client.get_json("/repos/{fn}".format(fn=full_name))
