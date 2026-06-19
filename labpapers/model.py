"""Dataclasses for papers and authors, plus impact-signal computation.

The impact signal is the heart of the "giant-weight" organizing principle:
fresh papers have ~0 citations, so per-paper ranking comes mostly from the
prominence of a paper's authors.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from . import config


@dataclass
class PaperAuthor:
    """An author as it appears on a paper, enriched with prominence later."""

    name: str
    openalex_id: Optional[str] = None
    institution_ids: List[str] = field(default_factory=list)
    raw_affiliation_strings: List[str] = field(default_factory=list)
    # filled in by the prominence engine:
    cited_by_count: int = 0
    h_index: int = 0
    works_count: int = 0
    last_institution_name: Optional[str] = None
    prominence_known: bool = False
    is_giant: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Author:
    """A researcher in the key-people ranking."""

    openalex_id: str
    name: str
    cited_by_count: int = 0
    h_index: int = 0
    works_count: int = 0
    last_institution_name: Optional[str] = None
    lab: Optional[str] = None
    is_giant: bool = False
    # Whether the author's OpenAlex profile is in AI/ML/CS. Used to keep the
    # Key People ranking free of non-CS researchers OpenAlex mis-tags to a lab.
    is_cs: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Paper:
    """A matched GenAI paper from one or both engines."""

    title: str
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    authors: List[PaperAuthor] = field(default_factory=list)
    date: Optional[str] = None  # publication date, YYYY-MM-DD
    abstract: str = ""
    cited_by_count: int = 0
    abs_url: Optional[str] = None
    pdf_url: Optional[str] = None
    doi_url: Optional[str] = None
    source_url: Optional[str] = None
    primary_category: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    # OpenAlex structured topic signal (the PRIMARY GenAI-scope classifier input
    # for OpenAlex-sourced works; empty for arXiv/site records, which classify by
    # category instead). Populated by openalex.normalize_work.
    primary_topic: Optional[str] = None
    primary_field: Optional[str] = None
    primary_subfield: Optional[str] = None
    topic_fields: List[str] = field(default_factory=list)
    labs_matched: List[str] = field(default_factory=list)
    # Watchlist tags (increment 3): configured person name(s) and institution
    # label(s) this paper was sourced for. A paper may carry both a lab and a
    # watchlist tag (union/dedup merges them).
    watchlist_people: List[str] = field(default_factory=list)
    watchlist_institution: List[str] = field(default_factory=list)
    source_engines: List[str] = field(default_factory=list)
    affiliation_evidence: List[str] = field(default_factory=list)
    resolved_via: Optional[str] = None

    # computed impact fields
    max_author_cited_by: int = 0
    sum_author_cited_by: int = 0
    has_giant_author: bool = False
    prominence_available: bool = False

    def identity_keys(self) -> List[str]:
        """All stable identities for union/dedup.

        A paper is the same as another when ANY identity matches: versionless
        arXiv id, DOI, source url, or normalized title. Source url is an
        ADDITIONAL identity (it de-dupes a site post discovered via both the
        listing and the sitemap) -- it never replaces normalized-title dedup, so
        OpenAlex/site duplicates that carry different urls but the same title
        still collapse into one paper.
        """

        keys: List[str] = []
        if self.arxiv_id:
            keys.append("arxiv:" + self.arxiv_id.lower())
        if self.doi:
            keys.append("doi:" + normalize_doi(self.doi))
        if self.source_url:
            keys.append("url:" + self.source_url.strip().lower())
        title = normalize_title(self.title)
        if title:
            keys.append("title:" + title)
        return keys

    def sort_key(self) -> Tuple[int, int, int, str]:
        """Descending sort key implementing impact_signal()."""

        return (
            self.max_author_cited_by,
            self.sum_author_cited_by,
            self.cited_by_count,
            self.date or "",
        )

    def impact_summary(self) -> str:
        if not self.prominence_available:
            return "prominence unavailable"
        return (
            "max author citations {max}, sum {sum}, paper citations {pc}".format(
                max=self.max_author_cited_by,
                sum=self.sum_author_cited_by,
                pc=self.cited_by_count,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["impact_summary"] = self.impact_summary()
        return d


def normalize_doi(doi: Optional[str]) -> str:
    if not doi:
        return ""
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d


def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    out = []
    for ch in title.lower():
        if ch.isalnum() or ch.isspace():
            out.append(ch)
    return " ".join("".join(out).split())


def compute_impact(
    paper: Paper,
    giant_cited_by: int = config.GIANT_CITED_BY,
    giant_hindex: int = config.GIANT_HINDEX,
) -> Paper:
    """Compute impact fields on a paper from its (already-enriched) authors.

    A paper's prominence is "available" when at least one author carries an
    OpenAlex id (and therefore looked-up prominence). Papers found only via the
    arXiv HTML fallback have no author ids, so they get signal 0 and are flagged
    "prominence unavailable".
    """

    citeds: List[int] = []
    has_giant = False
    prominence_available = False

    for author in paper.authors:
        if author.openalex_id:
            prominence_available = True
        if author.prominence_known:
            citeds.append(author.cited_by_count)
            author.is_giant = (
                author.cited_by_count >= giant_cited_by
                or author.h_index >= giant_hindex
            )
            if author.is_giant:
                has_giant = True

    paper.max_author_cited_by = max(citeds) if citeds else 0
    paper.sum_author_cited_by = sum(citeds) if citeds else 0
    paper.has_giant_author = has_giant
    paper.prominence_available = prominence_available
    return paper


def sort_papers(papers: List[Paper]) -> List[Paper]:
    """Sort papers by impact signal, descending."""

    return sorted(papers, key=lambda p: p.sort_key(), reverse=True)
