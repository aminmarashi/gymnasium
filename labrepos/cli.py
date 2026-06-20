"""Command-line entry point for the labrepos tracker."""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from typing import List, Optional

from . import config
from .pipeline import Options, run
from .report import write_reports


def _csv(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="labrepos",
        description=(
            "Surface NEW and recently-active GitHub repos created or "
            "contributed to by AI-research giants and leading coding / dev-AI "
            "orgs and people -- giant-attribution + recency + a GenAI/agentic "
            "topic filter, sorted by freshness."
        ),
    )
    p.add_argument(
        "--days", type=int, default=config.DEFAULT_DAYS,
        help="lookback window in days (default: %d)" % config.DEFAULT_DAYS,
    )
    p.add_argument(
        "--giants", type=_csv, default=list(config.GIANTS.keys()),
        help="comma-separated giant keys (default: all): "
             + ",".join(config.GIANTS.keys()),
    )
    p.add_argument(
        "--out", dest="out_dir", default="reports",
        help="output directory (default: reports)",
    )
    p.add_argument(
        "--format", dest="fmt", choices=["md", "json", "both"], default="both",
        help="output format (default: both)",
    )
    p.add_argument(
        "--cache-dir", default="data/cache",
        help="on-disk cache directory; empty string disables (default: data/cache)",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
        help="GitHub token (env GITHUB_TOKEN or GH_TOKEN)",
    )
    p.add_argument(
        "--max-pages", type=int, default=10,
        help="max repo-listing pages to scan per org/user (default: 10)",
    )
    p.add_argument(
        "--no-keyword-filter", dest="require_keyword", action="store_false",
        help="disable the GenAI/agentic topic filter (keep every in-window repo)",
    )
    p.add_argument(
        "--include-forks", dest="include_forks", action="store_true",
        help="include forks (dropped by default)",
    )
    p.add_argument(
        "--notable-stars", type=int, default=config.NOTABLE_STARS,
        help="star threshold for the notable mark (default: %d)"
             % config.NOTABLE_STARS,
    )
    p.add_argument(
        "--no-people", dest="include_people", action="store_false",
        help="skip the watchlist-people sources (owned + contributed-to repos)",
    )
    p.add_argument(
        "--top-per-giant", type=int, default=15,
        help="max repos rendered per giant in the Markdown report; "
             "0 or less shows all (JSON always keeps every repo) (default: 15)",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cache_dir = args.cache_dir if args.cache_dir else None

    opts = Options(
        days=args.days,
        giants=args.giants,
        out_dir=args.out_dir,
        fmt=args.fmt,
        cache_dir=cache_dir,
        token=args.token,
        max_pages=args.max_pages,
        require_keyword=args.require_keyword,
        include_forks=args.include_forks,
        notable_stars=args.notable_stars,
        include_people=args.include_people,
        top_per_giant=args.top_per_giant,
    )

    if not config.selected_giants(opts.giants):
        parser.error("no valid giants selected; choose from: %s"
                     % ",".join(config.GIANTS.keys()))

    if not opts.token:
        print(
            "labrepos: no GitHub token set (GITHUB_TOKEN/GH_TOKEN); "
            "unauthenticated requests are limited to 60/hr -- "
            "set a token to avoid throttling.",
            file=sys.stderr,
        )

    generated_at = _dt.datetime.now().isoformat(timespec="seconds")
    print(
        "labrepos: scanning {d} day(s) for {n} giant(s)...".format(
            d=opts.days, n=len(config.selected_giants(opts.giants))
        ),
        file=sys.stderr,
    )

    result = run(opts)

    paths = write_reports(
        result, opts.out_dir, fmt=opts.fmt, generated_at=generated_at,
        top_per_giant=opts.top_per_giant,
    )

    _print_summary(result, paths)
    return 0


def _print_summary(result, paths: List[str]) -> None:
    counts = ", ".join(
        "{g}={n}".format(g=k, n=result.per_giant_counts.get(k, 0))
        for k in result.giants
    )
    print(
        "Window {frm}..{to} | {total} repos | {counts}".format(
            frm=result.from_date,
            to=result.to_date,
            total=len(result.repos),
            counts=counts,
        )
    )
    top = result.repos[:5]
    if top:
        freshest = "; ".join(
            "{fn} ({s:,})".format(fn=r.full_name, s=r.stargazers_count)
            for r in top
        )
        print("Freshest: " + freshest)
    for path in paths:
        print("Wrote " + path)


if __name__ == "__main__":
    raise SystemExit(main())
