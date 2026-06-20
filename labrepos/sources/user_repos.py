"""Watchlist source: repos OWNED by tracked people.

For each watchlist username we scan ``/users/{user}/repos`` sorted by ``pushed``
descending with the same early stop as the org source, then keep in-window,
non-fork, GenAI/agentic repos. Person-sourced repos carry the synthetic
``people`` giant; if the repo's owner org is itself a configured giant, the
pipeline dedup/merge also attaches that giant.

Each per-user scan is wrapped in try/except so one bad username never aborts the
source or the others.
"""

from __future__ import annotations

from typing import Dict, List

from .. import config, watchlist as watchlist_config
from ..model import Repo, parse_repo
from .base import FetchContext, topic_filter


class UserReposSource:
    name = "user-repos"

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
        cache_key = "{user}|{frm}|{to}|{fork}".format(
            user=user.lower(), frm=ctx.from_date, to=ctx.to_date,
            fork=ctx.include_forks,
        )
        cached = ctx.cache.get("user-repos", cache_key)
        if cached is not None:
            raw = cached
        else:
            raw = []
            pages = ctx.client.iter_pages(
                "/users/{user}/repos".format(user=user),
                {"sort": "pushed", "direction": "desc"},
                ctx.max_pages,
            )
            stop = False
            for page in pages:
                for obj in page:
                    pushed = (obj or {}).get("pushed_at") or ""
                    if pushed and pushed < ctx.from_date:
                        stop = True
                        break
                    raw.append(obj)
                if stop:
                    break
            ctx.cache.set("user-repos", cache_key, raw)

        out: List[Repo] = []
        for obj in raw:
            repo = parse_repo(obj)
            if repo.is_fork and not ctx.include_forks:
                continue
            pushed = repo.pushed_at or ""
            if not pushed or pushed < ctx.from_date:
                continue
            repo.giants_matched = [config.PEOPLE_GIANT_KEY]
            repo.source_engines = [self.name]
            repo.matched_via = ["user:{user}".format(user=user)]
            # If the owner org is itself a configured giant, attach it too.
            owner_giant = config.giant_for_org(repo.owner)
            if owner_giant and owner_giant not in repo.giants_matched:
                repo.giants_matched.append(owner_giant)
            if topic_filter(repo, ctx.require_keyword):
                out.append(repo)
        return out
