import json
import os

from labrepos import report
from labrepos.model import Repo
from labrepos.pipeline import Result


def _build_result():
    new_notable = Repo(
        full_name="anthropics/claude-agent-sdk",
        owner="anthropics", name="claude-agent-sdk",
        description="An agentic coding SDK.",
        html_url="https://github.com/anthropics/claude-agent-sdk",
        language="Python", stargazers_count=1200, topics=["llm", "agentic"],
        created_at="2026-06-10T00:00:00Z", pushed_at="2026-06-19T00:00:00Z",
        giants_matched=["anthropic"], source_engines=["org-repos"],
        new_in_window=True, active_in_window=True, is_notable=True,
    )
    active_small = Repo(
        full_name="cline/cline",
        owner="cline", name="cline", description="An autonomous coding agent.",
        html_url="https://github.com/cline/cline",
        language="TypeScript", stargazers_count=40, topics=["ai-agent"],
        created_at="2024-01-01T00:00:00Z", pushed_at="2026-06-18T00:00:00Z",
        giants_matched=["cline"], source_engines=["org-repos"],
        new_in_window=False, active_in_window=True, is_notable=False,
    )
    people_repo = Repo(
        full_name="karpathy/nanochat",
        owner="karpathy", name="nanochat", description="A tiny LLM chat app.",
        html_url="https://github.com/karpathy/nanochat",
        language="Python", stargazers_count=900, topics=["llm"],
        created_at="2026-06-15T00:00:00Z", pushed_at="2026-06-19T00:00:00Z",
        giants_matched=["people"], source_engines=["user-repos"],
        new_in_window=True, active_in_window=True, is_notable=True,
    )
    return Result(
        repos=[new_notable, people_repo, active_small],
        from_date="2026-05-21",
        to_date="2026-06-20",
        giants=["anthropic", "cline", "people"],
        per_giant_counts={"anthropic": 1, "cline": 1, "people": 1},
        notable_stars=500,
    )


def test_markdown_groups_and_marks():
    md = report.render_markdown(_build_result(), generated_at="2026-06-20T00:00:00")
    assert "## Repos by giant" in md
    assert "### Anthropic (1)" in md
    assert "### Cline (1)" in md
    assert "### Watchlist people (1)" in md
    assert "\U0001F31F" in md  # notable star somewhere
    assert "new" in md
    assert "active" in md
    # notable repo carries the star on its stars line; small one does not.
    assert "stars 1,200 \U0001F31F" in md
    assert "stars 40\n" in md or "stars 40 " in md


def test_json_shape():
    js = report.render_json(_build_result(), generated_at="2026-06-20T00:00:00")
    data = json.loads(js)
    assert data["window"] == {"from": "2026-05-21", "to": "2026-06-20"}
    assert data["per_giant_counts"]["anthropic"] == 1
    assert data["notable_stars"] == 500
    assert len(data["repos"]) == 3
    assert data["repos"][0]["full_name"]


def _build_capped_result(n=20):
    repos = []
    for i in range(n):
        repos.append(Repo(
            full_name="anthropic-team/repo-%02d" % i,
            owner="anthropic-team", name="repo-%02d" % i,
            description="Repo number %d." % i,
            html_url="https://github.com/anthropic-team/repo-%02d" % i,
            language="Python", stargazers_count=100 + i, topics=["llm"],
            created_at="2026-06-10T00:00:00Z", pushed_at="2026-06-19T00:00:00Z",
            giants_matched=["anthropic"], source_engines=["org-repos"],
            new_in_window=True, active_in_window=True, is_notable=False,
        ))
    return Result(
        repos=repos,
        from_date="2026-05-21",
        to_date="2026-06-20",
        giants=["anthropic"],
        per_giant_counts={"anthropic": n},
        notable_stars=500,
    )


def test_markdown_caps_per_giant_display():
    n = 20
    cap = 15
    md = report.render_markdown(
        _build_capped_result(n), generated_at="2026-06-20T00:00:00",
        top_per_giant=cap,
    )
    # Header keeps the TRUE total, not the capped number.
    assert "### Anthropic (%d)" % n in md
    # Exactly `cap` repo entries rendered.
    assert md.count("#### [") == cap
    # The freshest `cap` are shown; the rest are hidden.
    assert "repo-00" in md
    assert "repo-%02d" % (cap - 1) in md
    assert "repo-%02d" % cap not in md
    # '+X more' note appended after the capped list.
    assert (
        "_+%d more — raise --top-per-giant "
        "(use --top-per-giant 0 to show all)_" % (n - cap)
    ) in md


def test_markdown_cap_zero_disables():
    n = 20
    md = report.render_markdown(
        _build_capped_result(n), generated_at="2026-06-20T00:00:00",
        top_per_giant=0,
    )
    assert md.count("#### [") == n
    assert "### Anthropic (%d)" % n in md
    assert "more — raise --top-per-giant" not in md


def test_json_keeps_all_repos_despite_cap():
    n = 20
    # JSON has no cap parameter; it must always retain every repo.
    js = report.render_json(
        _build_capped_result(n), generated_at="2026-06-20T00:00:00"
    )
    data = json.loads(js)
    assert len(data["repos"]) == n
    assert data["per_giant_counts"]["anthropic"] == n


def test_write_reports_creates_files(tmp_path):
    paths = report.write_reports(
        _build_result(), str(tmp_path), fmt="both",
        generated_at="2026-06-20T00:00:00",
    )
    assert len(paths) == 2
    names = sorted(os.path.basename(p) for p in paths)
    assert names == ["labrepos_2026-06-20_30d.json", "labrepos_2026-06-20_30d.md"]
    for p in paths:
        with open(p) as fh:
            assert fh.read().strip()
