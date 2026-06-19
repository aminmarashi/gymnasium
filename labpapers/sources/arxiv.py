"""arXiv engine: a recent-by-category candidate pool via the Atom API.

arXiv exposes no usable author-affiliation filter, so this engine pulls a broad,
freshness-sorted candidate pool by category. Topic-filtering and affiliation
resolution happen downstream.
"""

from __future__ import annotations

import time
from typing import List, Optional

import feedparser

from ..http import HttpClient
from ..model import Paper, PaperAuthor

ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_DOI_PREFIX = "10.48550/arXiv."


def _versionless(arxiv_url_or_id: str) -> Optional[str]:
    """'http://arxiv.org/abs/2401.01234v2' -> '2401.01234'."""

    if not arxiv_url_or_id:
        return None
    ident = arxiv_url_or_id.rstrip("/").rsplit("/", 1)[-1]
    # strip version suffix vN
    if "v" in ident:
        head, _, tail = ident.rpartition("v")
        if tail.isdigit():
            ident = head
    return ident or None


def _date_only(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value[:10]


def parse_feed(text: str) -> List[Paper]:
    """Parse an arXiv Atom feed body into Paper records.

    Pure function (no network) so it can be unit-tested from a saved fixture.
    """

    feed = feedparser.parse(text)
    papers: List[Paper] = []
    for entry in feed.entries:
        arxiv_id = _versionless(entry.get("id", ""))
        if not arxiv_id:
            continue

        authors: List[PaperAuthor] = []
        for a in entry.get("authors", []) or []:
            name = a.get("name") if isinstance(a, dict) else getattr(a, "name", None)
            if name:
                authors.append(PaperAuthor(name=name))

        categories: List[str] = []
        for tag in entry.get("tags", []) or []:
            term = tag.get("term") if isinstance(tag, dict) else getattr(tag, "term", None)
            if term:
                categories.append(term)

        primary = None
        prim = entry.get("arxiv_primary_category")
        if isinstance(prim, dict):
            primary = prim.get("term")
        if not primary and categories:
            primary = categories[0]

        abs_url = None
        pdf_url = None
        for link in entry.get("links", []) or []:
            rel = link.get("rel")
            ltype = link.get("type")
            href = link.get("href")
            if ltype == "application/pdf" or link.get("title") == "pdf":
                pdf_url = href
            elif rel == "alternate":
                abs_url = href
        if not abs_url:
            abs_url = "https://arxiv.org/abs/" + arxiv_id

        # arXiv's own DOI is deterministic; a journal DOI (if any) is separate.
        arxiv_doi = ARXIV_DOI_PREFIX + arxiv_id

        papers.append(Paper(
            title=" ".join((entry.get("title") or "").split()),
            arxiv_id=arxiv_id,
            doi=entry.get("arxiv_doi") or arxiv_doi,
            authors=authors,
            date=_date_only(entry.get("published")),
            abstract=" ".join((entry.get("summary") or "").split()),
            abs_url=abs_url,
            pdf_url=pdf_url,
            source_url=abs_url,
            primary_category=primary,
            categories=categories,
            source_engines=["arxiv"],
        ))
    return papers


def recent_candidates(
    client: HttpClient,
    categories: List[str],
    from_date: str,
    max_pages: int = 10,
    page_size: int = 200,
    delay: float = 3.0,
) -> List[Paper]:
    """Page the arXiv API newest-first, stopping once we pass the window.

    ``from_date`` is an inclusive 'YYYY-MM-DD' lower bound on the published
    date. We stop as soon as a page's newest entry is older than that.
    """

    search_query = " OR ".join("cat:" + c for c in categories)
    collected: List[Paper] = []
    seen = set()
    for page in range(max_pages):
        params = {
            "search_query": search_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": page * page_size,
            "max_results": page_size,
        }
        text = client.get_text(ARXIV_API, params=params)
        if not text:
            break
        page_papers = parse_feed(text)
        if not page_papers:
            break

        page_min_date = None
        added_any = False
        for paper in page_papers:
            if paper.arxiv_id in seen:
                continue
            if paper.date is not None:
                if page_min_date is None or paper.date < page_min_date:
                    page_min_date = paper.date
            if paper.date is not None and paper.date < from_date:
                continue
            seen.add(paper.arxiv_id)
            collected.append(paper)
            added_any = True

        # Stop once the whole page is older than the window.
        if page_min_date is not None and page_min_date < from_date:
            break
        if not added_any:
            break
        if page < max_pages - 1 and delay > 0:
            time.sleep(delay)
    return collected
