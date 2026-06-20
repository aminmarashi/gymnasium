"""Render the run result as Markdown and JSON.

Markdown leads with the window / giants / per-giant counts and a one-line note
explaining the freshness sort, then a per-giant section (labs first, coding
second, the synthetic people bucket last) of repos sorted by freshness.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import List, Optional

from . import config
from .model import Repo
from .pipeline import Result, repos_for_giant


def _notable_mark(flag: bool) -> str:
    return " \U0001F31F" if flag else ""  # star


def render_markdown(
    result: Result,
    generated_at: Optional[str] = None,
    top_per_giant: int = 15,
) -> str:
    lines: List[str] = []
    lines.append("# GitHub giant-attribution tracker (labrepos)")
    lines.append("")
    window = "{frm} → {to}".format(frm=result.from_date, to=result.to_date)
    lines.append("- **Window:** {window}".format(window=window))
    lines.append(
        "- **Giants:** {giants}".format(
            giants=", ".join(
                config.giant_display_name(k) for k in result.giants
            )
        )
    )
    if generated_at:
        lines.append("- **Generated:** {ts}".format(ts=generated_at))
    lines.append("- **Total repos:** {n}".format(n=len(result.repos)))
    counts = ", ".join(
        "{g}: {n}".format(
            g=config.giant_display_name(k), n=result.per_giant_counts.get(k, 0)
        )
        for k in result.giants
    )
    lines.append("- **Per-giant counts:** {counts}".format(counts=counts))
    lines.append("")
    lines.append(
        "> Sorted by **freshness** (new-in-window first, then most recently "
        "pushed, then stars) so the newest work rises to the top. \U0001F31F "
        "marks an already-notable repo (stars ≥ {n:,}).".format(
            n=result.notable_stars
        )
    )
    lines.append("")

    lines.append("## Repos by giant")
    lines.append("")
    for key in result.giants:
        giant_repos = repos_for_giant(result.repos, key)
        lines.append("### {g} ({n})".format(
            g=config.giant_display_name(key), n=len(giant_repos)
        ))
        lines.append("")
        if not giant_repos:
            lines.append("_No matched repos in window._")
            lines.append("")
            continue
        if top_per_giant > 0 and len(giant_repos) > top_per_giant:
            shown = giant_repos[:top_per_giant]
            hidden = len(giant_repos) - top_per_giant
        else:
            shown = giant_repos
            hidden = 0
        for repo in shown:
            lines.extend(_render_repo(repo))
            lines.append("")
        if hidden:
            lines.append(
                "_+{x} more — raise --top-per-giant "
                "(use --top-per-giant 0 to show all)_".format(x=hidden)
            )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_repo(repo: Repo) -> List[str]:
    full_name = repo.full_name or "(unknown)"
    if repo.html_url:
        header = "#### [{fn}]({u})".format(fn=full_name, u=repo.html_url)
    else:
        header = "#### {fn}".format(fn=full_name)
    out = [header]

    meta: List[str] = []
    if repo.new_in_window:
        meta.append("new")
    elif repo.active_in_window:
        meta.append("active")
    if repo.pushed_at:
        meta.append("pushed {d}".format(d=_date_only(repo.pushed_at)))
    if repo.created_at:
        meta.append("created {d}".format(d=_date_only(repo.created_at)))
    meta.append("stars {s:,}{mark}".format(
        s=repo.stargazers_count, mark=_notable_mark(repo.is_notable)
    ))
    if repo.language:
        meta.append("lang {l}".format(l=repo.language))
    if repo.topics:
        meta.append("topics {t}".format(t=", ".join(repo.topics[:6])))
    if repo.source_engines:
        meta.append("via {e}".format(e=", ".join(repo.source_engines)))
    out.append("- " + " | ".join(meta))

    if repo.description:
        desc = repo.description.strip().replace("\n", " ")
        out.append("")
        out.append("> " + desc)
    return out


def _date_only(ts: Optional[str]) -> str:
    if not ts:
        return ""
    return ts[:10]


def render_json(result: Result, generated_at: Optional[str] = None) -> str:
    payload = {
        "window": {"from": result.from_date, "to": result.to_date},
        "generated_at": generated_at,
        "giants": result.giants,
        "per_giant_counts": result.per_giant_counts,
        "notable_stars": result.notable_stars,
        "repos": [r.to_dict() for r in result.repos],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def write_reports(
    result: Result,
    out_dir: str,
    fmt: str = "both",
    generated_at: Optional[str] = None,
    top_per_giant: int = 15,
) -> List[str]:
    """Write requested formats and return the paths written."""

    os.makedirs(out_dir, exist_ok=True)
    days = _window_days(result)
    base = "labrepos_{stamp}_{days}d".format(stamp=result.to_date, days=days)
    written: List[str] = []

    if fmt in ("md", "both"):
        path = os.path.join(out_dir, base + ".md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(result, generated_at, top_per_giant))
        written.append(path)
    if fmt in ("json", "both"):
        path = os.path.join(out_dir, base + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_json(result, generated_at))
        written.append(path)
    return written


def _window_days(result: Result) -> int:
    try:
        frm = _dt.date.fromisoformat(result.from_date)
        to = _dt.date.fromisoformat(result.to_date)
        return (to - frm).days
    except ValueError:
        return 0
