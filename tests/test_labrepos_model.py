from labrepos.model import (
    Repo, compute_signal, merge_into, parse_repo, sort_repos,
)

ORG_OBJ = {
    "full_name": "anthropics/claude-agent-sdk",
    "name": "claude-agent-sdk",
    "owner": {"login": "anthropics"},
    "description": "Agentic SDK.",
    "html_url": "https://github.com/anthropics/claude-agent-sdk",
    "language": "Python",
    "stargazers_count": 1200,
    "forks_count": 80,
    "open_issues_count": 12,
    "created_at": "2026-06-10T10:00:00Z",
    "pushed_at": "2026-06-19T09:00:00Z",
    "topics": ["llm", "agentic"],
    "fork": False,
    "archived": False,
}


def test_parse_repo_basic():
    r = parse_repo(ORG_OBJ, matched_giant="anthropic", source_engine="org-repos",
                   matched_via="org:anthropics")
    assert r.full_name == "anthropics/claude-agent-sdk"
    assert r.owner == "anthropics"
    assert r.name == "claude-agent-sdk"
    assert r.stargazers_count == 1200
    assert r.topics == ["llm", "agentic"]
    assert r.giants_matched == ["anthropic"]
    assert r.source_engines == ["org-repos"]
    assert r.matched_via == ["org:anthropics"]


def test_parse_repo_tolerates_missing_fields():
    r = parse_repo({"full_name": "o/r"})
    assert r.full_name == "o/r"
    assert r.owner == "o"
    assert r.name == "r"
    assert r.stargazers_count == 0
    assert r.topics == []


def test_compute_signal_new():
    r = parse_repo(ORG_OBJ)
    compute_signal(r, "2026-06-01", notable_stars=500)
    assert r.new_in_window is True       # created 2026-06-10 >= from
    assert r.active_in_window is True     # pushed in window too
    assert r.is_notable is True           # 1200 >= 500


def test_compute_signal_active_not_new():
    obj = dict(ORG_OBJ, created_at="2025-01-01T00:00:00Z",
               pushed_at="2026-06-18T00:00:00Z", stargazers_count=10)
    r = parse_repo(obj)
    compute_signal(r, "2026-06-01", notable_stars=500)
    assert r.new_in_window is False
    assert r.active_in_window is True
    assert r.is_notable is False


def test_freshness_key_ordering():
    new_low = parse_repo(dict(ORG_OBJ, full_name="o/new",
                              created_at="2026-06-10T00:00:00Z",
                              pushed_at="2026-06-11T00:00:00Z",
                              stargazers_count=1))
    active_high = parse_repo(dict(ORG_OBJ, full_name="o/active",
                                  created_at="2024-01-01T00:00:00Z",
                                  pushed_at="2026-06-19T00:00:00Z",
                                  stargazers_count=9999))
    for r in (new_low, active_high):
        compute_signal(r, "2026-06-01", notable_stars=500)
    ordered = sort_repos([active_high, new_low])
    # new beats active regardless of stars / pushed date
    assert ordered[0].full_name == "o/new"
    assert ordered[1].full_name == "o/active"


def test_merge_into_unions_and_ors():
    a = Repo(full_name="o/r", giants_matched=["anthropic"],
             source_engines=["org-repos"], matched_via=["org:anthropics"],
             new_in_window=True, is_notable=False, stargazers_count=10)
    b = Repo(full_name="o/r", giants_matched=["people"],
             source_engines=["user-repos"], matched_via=["user:karpathy"],
             new_in_window=False, is_notable=True, stargazers_count=20)
    merge_into(a, b)
    assert a.giants_matched == ["anthropic", "people"]
    assert a.source_engines == ["org-repos", "user-repos"]
    assert a.matched_via == ["org:anthropics", "user:karpathy"]
    assert a.new_in_window is True
    assert a.is_notable is True
    assert a.stargazers_count == 20
