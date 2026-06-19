"""Command-line entry point for the labpapers tracker."""

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
        prog="labpapers",
        description=(
            "Track recent GenAI papers from six labs (Anthropic, Meta, Google "
            "incl. DeepMind, OpenAI, Z.AI/Zhipu, DeepSeek) and rank both papers "
            "and researchers by author prominence (giant-weight)."
        ),
    )
    p.add_argument(
        "--days", type=int, default=7,
        help="lookback window in days (default: 7)",
    )
    p.add_argument(
        "--labs", type=_csv, default=list(config.LABS.keys()),
        help="comma-separated lab keys: " + ",".join(config.LABS.keys()),
    )
    p.add_argument(
        "--categories", type=_csv, default=list(config.DEFAULT_CATEGORIES),
        help="comma-separated arXiv categories (default: %s)"
             % ",".join(config.DEFAULT_CATEGORIES),
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
        "--concurrency", type=int, default=6,
        help="threads for the arXiv HTML fallback (default: 6)",
    )
    p.add_argument(
        "--cache-dir", default="data/cache",
        help="on-disk cache directory; empty string disables (default: data/cache)",
    )
    p.add_argument(
        "--mailto", default=os.environ.get("OPENALEX_MAILTO"),
        help="contact email for the OpenAlex polite pool (env OPENALEX_MAILTO)",
    )
    p.add_argument(
        "--no-fulltext", dest="fulltext", action="store_false",
        help="skip the arxiv.org/html affiliation fallback (faster, smaller)",
    )
    p.add_argument(
        "--max-pages", type=int, default=10,
        help="max arXiv result pages to scan (default: 10)",
    )
    p.add_argument(
        "--top-people", type=int, default=25,
        help="number of people to rank per lab and overall (default: 25)",
    )
    p.add_argument(
        "--giant-cited-by", type=int, default=config.GIANT_CITED_BY,
        help="citation threshold for the giant flag (default: %d)"
             % config.GIANT_CITED_BY,
    )
    p.add_argument(
        "--giant-hindex", type=int, default=config.GIANT_HINDEX,
        help="h-index threshold for the giant flag (default: %d)"
             % config.GIANT_HINDEX,
    )
    p.add_argument(
        "--no-keyword-filter", dest="require_keyword", action="store_false",
        help="do not require a GenAI keyword for non-cs.CL papers",
    )
    p.add_argument(
        "--no-watchlist", dest="watchlist", action="store_false",
        help="skip the Netherlands GenAI map / watchlist section",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cache_dir = args.cache_dir if args.cache_dir else None

    opts = Options(
        days=args.days,
        labs=args.labs,
        categories=args.categories,
        out_dir=args.out_dir,
        fmt=args.fmt,
        concurrency=args.concurrency,
        cache_dir=cache_dir,
        mailto=args.mailto,
        fulltext=args.fulltext,
        max_pages=args.max_pages,
        top_people=args.top_people,
        giant_cited_by=args.giant_cited_by,
        giant_hindex=args.giant_hindex,
        require_keyword=args.require_keyword,
        watchlist=args.watchlist,
    )

    if not config.selected_labs(opts.labs):
        parser.error("no valid labs selected; choose from: %s"
                     % ",".join(config.LABS.keys()))

    generated_at = _dt.datetime.now().isoformat(timespec="seconds")
    print(
        "labpapers: scanning {d} day(s) for {n} lab(s)...".format(
            d=opts.days, n=len(config.selected_labs(opts.labs))
        ),
        file=sys.stderr,
    )

    result = run(opts)

    paths = write_reports(
        result, opts.out_dir, fmt=opts.fmt, generated_at=generated_at
    )

    _print_summary(result, paths)
    return 0


def _print_summary(result, paths: List[str]) -> None:
    counts = ", ".join(
        "{lab}={n}".format(lab=k, n=result.per_lab_counts.get(k, 0))
        for k in result.labs
    )
    print(
        "Window {frm}..{to} | {total} papers | {counts}".format(
            frm=result.from_date,
            to=result.to_date,
            total=len(result.papers),
            counts=counts,
        )
    )
    top = result.people_overall[:5]
    if top:
        people = "; ".join(
            "{name} ({c:,} cites)".format(name=a.name, c=a.cited_by_count)
            for a in top
        )
        print("Top people: " + people)
    for path in paths:
        print("Wrote " + path)


if __name__ == "__main__":
    raise SystemExit(main())
