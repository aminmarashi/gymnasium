import datetime
import os

from labrepos.cache import Cache
from labrepos.sources.base import FetchContext
from labrepos.sources.org_repos import OrgReposSource
from tests.test_labrepos_pipeline import FakeGithubClient, _load

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _ctx(client):
    return FetchContext(
        from_date="2026-05-21",
        to_date="2026-06-20",
        giant_keys=["anthropic"],
        client=client,
        cache=Cache(None, enabled=False),
        days=30,
        max_pages=10,
        require_keyword=True,
        include_forks=False,
        notable_stars=500,
    )


def test_org_source_parses_and_filters():
    org_page = _load("github_org_repos.json")
    client = FakeGithubClient(pages_by_path={"/orgs/anthropics/repos": [org_page]})
    repos = OrgReposSource().fetch(_ctx(client))
    names = {r.full_name for r in repos}
    assert names == {
        "anthropics/claude-agent-sdk", "anthropics/prompt-cookbook",
    }
    for r in repos:
        assert r.giants_matched == ["anthropic"]
        assert r.matched_via == ["org:anthropics"]


def test_org_source_stops_paging_at_out_of_window():
    org_page = _load("github_org_repos.json")
    # Page 0 ends with an out-of-window repo (old-llm-experiment); page 1 must
    # never be requested because the source breaks on the first stale push.
    extra_page = [dict(org_page[0], full_name="anthropics/should-not-load",
                       name="should-not-load")]
    client = FakeGithubClient(
        pages_by_path={"/orgs/anthropics/repos": [org_page, extra_page]},
    )
    repos = OrgReposSource().fetch(_ctx(client))
    names = {r.full_name for r in repos}
    assert "anthropics/should-not-load" not in names
    # Only page 0 was actually consumed.
    assert client.pages_served == [("/orgs/anthropics/repos", 0)]
