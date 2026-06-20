"""PRIMARY source: public repos owned by a selected giant's orgs.

For each org of each selected giant we scan ``/orgs/{org}/repos`` sorted by
``pushed`` descending and stop as soon as we hit a repo pushed before the window
-- the early stop that bounds huge orgs (facebookresearch ~1.4k, microsoft /
github / jetbrains hundreds). Because GitHub guarantees ``pushed_at >=
created_at``, this single pushed-sorted pass is COMPLETE for the "new OR active"
definition (a repo created in window is necessarily pushed in window too); we
drop forks, whose ``pushed_at`` could otherwise reflect upstream activity.

Every per-org scan is wrapped in try/except so one failing org degrades coverage
but never aborts the source or the other orgs.
"""

from __future__ import annotations

from typing import List

from .. import config
from ..model import Repo, parse_repo
from .base import FetchContext, topic_filter


class OrgReposSource:
    name = "org-repos"

    def fetch(self, ctx: FetchContext) -> List[Repo]:
        giants = config.selected_giants(ctx.giant_keys)
        out: List[Repo] = []
        for key, giant in giants.items():
            for org in giant.orgs:
                try:
                    out.extend(self._fetch_org(ctx, key, org))
                except Exception:
                    # One failing org degrades coverage, never the source.
                    continue
        return out

    def _fetch_org(self, ctx: FetchContext, giant_key: str, org: str) -> List[Repo]:
        cache_key = "{org}|{frm}|{to}|{fork}".format(
            org=org.lower(), frm=ctx.from_date, to=ctx.to_date,
            fork=ctx.include_forks,
        )
        cached = ctx.cache.get("org-repos", cache_key)
        if cached is not None:
            repos = [parse_repo(obj) for obj in cached]
            return self._tag_and_filter(ctx, giant_key, org, repos)

        in_window_raw: List[dict] = []
        pages = ctx.client.iter_pages(
            "/orgs/{org}/repos".format(org=org),
            {"type": "public", "sort": "pushed", "direction": "desc"},
            ctx.max_pages,
        )
        stop = False
        for page in pages:
            for obj in page:
                pushed = (obj or {}).get("pushed_at") or ""
                if pushed and pushed < ctx.from_date:
                    # pushed-desc: everything after this is older -> stop paging.
                    stop = True
                    break
                in_window_raw.append(obj)
            if stop:
                break

        ctx.cache.set("org-repos", cache_key, in_window_raw)
        repos = [parse_repo(obj) for obj in in_window_raw]
        return self._tag_and_filter(ctx, giant_key, org, repos)

    def _tag_and_filter(
        self, ctx: FetchContext, giant_key: str, org: str, repos: List[Repo]
    ) -> List[Repo]:
        out: List[Repo] = []
        for repo in repos:
            if repo.is_fork and not ctx.include_forks:
                continue
            pushed = repo.pushed_at or ""
            if not pushed or pushed < ctx.from_date:
                continue
            repo.giants_matched = [giant_key]
            repo.source_engines = [self.name]
            repo.matched_via = ["org:{org}".format(org=org)]
            if topic_filter(repo, ctx.require_keyword):
                out.append(repo)
        return out
