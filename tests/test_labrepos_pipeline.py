import os

from labrepos import config
from labrepos.model import Repo, compute_signal
from labrepos.pipeline import (
    Options, dedup_repos, repos_for_giant, run,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    import json
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


class FakeGithubClient:
    """Offline test double exposing get_json + iter_pages from fixtures."""

    def __init__(self, pages_by_path=None, json_by_path=None, errors=None):
        self.pages_by_path = pages_by_path or {}
        self.json_by_path = json_by_path or {}
        self.errors = set(errors or [])
        self.pages_served = []
        self.json_calls = []

    def get_json(self, path, params=None):
        self.json_calls.append(path)
        if path in self.errors:
            raise RuntimeError("boom: " + path)
        return self.json_by_path.get(path)

    def iter_pages(self, path, params=None, max_pages=10):
        if path in self.errors:
            raise RuntimeError("boom: " + path)
        pages = self.pages_by_path.get(path, [])
        for i, page in enumerate(pages):
            if i >= max_pages:
                break
            self.pages_served.append((path, i))
            yield page


TODAY = __import__("datetime").date(2026, 6, 20)


# --- pure helpers ----------------------------------------------------------
def test_dedup_transitive_merge_across_giants():
    a = Repo(full_name="Org/Repo", giants_matched=["anthropic"],
             source_engines=["org-repos"], matched_via=["org:anthropics"])
    b = Repo(full_name="org/repo", giants_matched=["people"],
             source_engines=["user-repos"], matched_via=["user:karpathy"])
    out = dedup_repos([a, b])
    assert len(out) == 1
    merged = out[0]
    assert set(merged.giants_matched) == {"anthropic", "people"}
    assert set(merged.source_engines) == {"org-repos", "user-repos"}


def test_repos_for_giant():
    a = Repo(full_name="o/a", giants_matched=["anthropic"])
    b = Repo(full_name="o/b", giants_matched=["people", "anthropic"])
    c = Repo(full_name="o/c", giants_matched=["people"])
    assert [r.full_name for r in repos_for_giant([a, b, c], "anthropic")] == \
        ["o/a", "o/b"]
    assert [r.full_name for r in repos_for_giant([a, b, c], "people")] == \
        ["o/b", "o/c"]


# --- run() through a fake client ------------------------------------------
def test_run_filters_groups_counts_and_sorts():
    org_page = _load("github_org_repos.json")
    client = FakeGithubClient(
        pages_by_path={"/orgs/anthropics/repos": [org_page]},
    )
    opts = Options(
        days=30, giants=["anthropic"], cache_dir=None,
        include_people=False, today=TODAY, notable_stars=500,
    )
    result = run(opts, client=client)

    names = [r.full_name for r in result.repos]
    # KEEPs: claude-agent-sdk (topics) + prompt-cookbook (keyword).
    assert "anthropics/claude-agent-sdk" in names
    assert "anthropics/prompt-cookbook" in names
    # Filtered out: non-GenAI, fork, out-of-window, bare-ambiguous false pos.
    assert "anthropics/heat-diffusion-solver" not in names
    assert "anthropics/brand-icons" not in names
    assert "anthropics/forked-llm-tool" not in names
    assert "anthropics/old-llm-experiment" not in names

    assert result.per_giant_counts["anthropic"] == 2
    # No people bucket when include_people is False.
    assert config.PEOPLE_GIANT_KEY not in result.giants

    # Freshest first: claude-agent-sdk (new + 1200 stars) leads.
    assert result.repos[0].full_name == "anthropics/claude-agent-sdk"
    assert result.repos[0].new_in_window is True
    assert result.repos[0].is_notable is True


def test_run_one_org_failure_does_not_sink_others():
    org_page = _load("github_org_repos.json")
    # meta giant owns facebookresearch + meta-llama; fail the first, serve the
    # second a good repo.
    good = dict(org_page[0], full_name="meta-llama/llama-agent",
                name="llama-agent", owner={"login": "meta-llama"})
    client = FakeGithubClient(
        pages_by_path={"/orgs/meta-llama/repos": [[good]]},
        errors={"/orgs/facebookresearch/repos"},
    )
    opts = Options(
        days=30, giants=["meta"], cache_dir=None,
        include_people=False, today=TODAY,
    )
    result = run(opts, client=client)
    names = [r.full_name for r in result.repos]
    assert "meta-llama/llama-agent" in names
    assert result.per_giant_counts["meta"] == 1


def test_run_includes_people_bucket_via_events():
    org_page = _load("github_org_repos.json")
    events = _load("github_user_events.json")
    # The events fixture references anthropics/claude-agent-sdk (owned by a
    # giant) and someuser/llm-router. Serve both repo objects.
    router = dict(org_page[0], full_name="someuser/llm-router",
                  name="llm-router", owner={"login": "someuser"},
                  stargazers_count=12, topics=["llm"])
    json_by_path = {
        "/repos/anthropics/claude-agent-sdk": org_page[0],
        "/repos/someuser/llm-router": router,
    }
    # All watchlist users return the same events page; user-repos return nothing.
    pages = {}
    from labrepos import watchlist as wl
    for p in wl.WATCHLIST_PEOPLE:
        json_by_path["/users/%s/events/public" % p["username"]] = events
    client = FakeGithubClient(
        pages_by_path={"/orgs/anthropics/repos": [org_page]},
        json_by_path=json_by_path,
    )
    opts = Options(
        days=30, giants=["anthropic"], cache_dir=None,
        include_people=True, today=TODAY,
    )
    result = run(opts, client=client)
    assert config.PEOPLE_GIANT_KEY in result.giants
    names = [r.full_name for r in result.repos]
    assert "someuser/llm-router" in names
    # The giant-owned repo seen via events merges onto the org record (deduped).
    sdk = [r for r in result.repos
           if r.full_name == "anthropics/claude-agent-sdk"][0]
    assert "anthropic" in sdk.giants_matched
    assert config.PEOPLE_GIANT_KEY in sdk.giants_matched
