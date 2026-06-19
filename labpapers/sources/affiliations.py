"""Resolve which labs authored each arXiv candidate paper.

This is the hybrid path that fills OpenAlex's blind spots (Anthropic & DeepSeek
have no usable institution id) and catches the very freshest papers OpenAlex has
not yet indexed:

  1. Bulk OpenAlex DOI lookup for the arXiv DOIs. Labs are derived from (a) the
     covered-lab institution ids and (b) regexes over the raw affiliation
     strings. This alone catches DeepSeek, whose affiliation text says
     "DeepSeek-AI" even though OpenAlex has no institution for it.
  2. HTML fallback (only when --fulltext is on AND the paper was not resolved
     by OpenAlex): fetch arxiv.org/html/<id> and regex-match the author /
     affiliation frontmatter. This is what catches Anthropic.

Per-paper results are cached. HTML fetches run on a small thread pool.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .. import config
from ..cache import Cache
from ..http import HttpClient
from ..model import Paper, PaperAuthor
from . import openalex


@dataclass
class Resolution:
    labs: List[str] = field(default_factory=list)
    authors: List[PaperAuthor] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    resolved_via: str = "unresolved"  # openalex | html | unresolved

    def to_cache(self) -> Dict:
        return {
            "labs": self.labs,
            "authors": [a.to_dict() for a in self.authors],
            "evidence": self.evidence,
            "resolved_via": self.resolved_via,
        }

    @staticmethod
    def from_cache(d: Dict) -> "Resolution":
        return Resolution(
            labs=list(d.get("labs") or []),
            authors=[PaperAuthor(**a) for a in (d.get("authors") or [])],
            evidence=list(d.get("evidence") or []),
            resolved_via=d.get("resolved_via") or "unresolved",
        )


def labs_from_authors(
    paper_authors: List[PaperAuthor], only: Optional[List[str]]
) -> "tuple[set, List[str]]":
    """Derive (lab keys, evidence) from a paper's author list.

    Three positive signals, in order: an exact org-collective byline
    ("DeepSeek-AI" -> deepseek), the covered-lab OpenAlex institution ids, and
    the affiliation-string regexes. Model-persona "authors" are skipped entirely
    so they cannot credit a lab (OpenAlex even hands them the real lab id).
    """

    inst_ids: List[str] = []
    affil_strings: List[str] = []
    labs: set = set()
    evidence: List[str] = []
    for a in paper_authors:
        lab = config.collective_author_lab(a.name)
        if lab is not None:
            if only is None or lab in only:
                labs.add(lab)
                evidence.append(" ".join(a.name.split()))
            continue
        if config.is_persona_author(a.name, a.raw_affiliation_strings):
            continue
        inst_ids.extend(a.institution_ids)
        affil_strings.extend(a.raw_affiliation_strings)

    labs |= config.match_labs_by_institution(inst_ids, only=only)
    by_affil = config.match_labs_by_affiliation(affil_strings, only=only)
    for lab, ev in by_affil.items():
        labs.add(lab)
        evidence.extend(ev)
    return labs, evidence


def _labs_from_work(
    work: Dict, only: Optional[List[str]]
) -> "tuple[List[str], List[str], List[PaperAuthor]]":
    """Derive (labs, evidence, authors) from one OpenAlex work record."""

    paper = openalex.normalize_work(work)
    labs, evidence = labs_from_authors(paper.authors, only)
    return sorted(labs), evidence, paper.authors


def _has_usable_affiliation_strings(authors: List[PaperAuthor]) -> bool:
    """Whether OpenAlex gave any usable raw affiliation TEXT to match on.

    Institution ids alone do NOT count: when no covered lab matched and the raw
    affiliation strings are empty (or only persona/multi-lab junk), the
    arxiv.org/html author block may still reveal the real affiliation -- the
    "OpenAlex-present-but-empty-affiliations" case (e.g. Anthropic, which has no
    OpenAlex institution id). So a paper is only *settled* as "not ours" when
    OpenAlex actually carries a clean, non-junk affiliation string we could have
    matched; otherwise we fall back to HTML.
    """

    for a in authors:
        for s in a.raw_affiliation_strings:
            if s and s.strip() and not config._affiliation_is_junk(s):
                return True
    return False


# Bump whenever the resolver semantics change so old cached resolutions (in
# particular stale "unresolved" false-negatives) are not reused on existing
# caches. v2: collective-author byline + DeepSeek detection, broader arXiv-HTML
# author-block resolution, and the OpenAlex-present-but-empty-affiliations HTML
# fallback. v3: HTML-fallback resolutions now retain the OpenAlex author ids, so
# v2 entries (which dropped them) must not be reused or those papers keep losing
# prominence. Folded into the cache key so older entries are simply never read.
_RESOLVER_CACHE_VERSION = "v3"


def _cache_key(arxiv_id: str, only: Optional[List[str]]) -> str:
    """Per-paper cache key, versioned and scoped by the lab filter.

    A Resolution is filtered by ``only``, so a ``--labs google`` run must not
    poison a later all-labs run by reusing its narrower match. Folding the sorted
    lab filter into the key keeps each filter's resolution separate, and the
    resolver-version prefix invalidates resolutions written by older semantics.
    """

    scope = ",".join(sorted(only)) if only is not None else "*"
    return _RESOLVER_CACHE_VERSION + "|" + arxiv_id + "|" + scope


# Cap on the length of any single affiliation string we keep, so a malformed
# page can never bloat the report or smuggle body text into the match.
MAX_AFFIL_LEN = 300

# LaTeXML/ar5iv class names that hold the *actual* affiliation frontmatter.
# We deliberately do NOT scan generic author containers or body text: matching
# a lab name in an abstract, intro, or reference list is a false positive.
_AFFIL_CLASSES = ("ltx_role_affiliation", "ltx_contact")


def _class_match(target):
    def predicate(value):
        if not value:
            return False
        classes = value if isinstance(value, list) else [value]
        joined = " ".join(classes)
        return target in joined
    return predicate


def parse_html_affiliations(html: str) -> List[str]:
    """Extract author *affiliation* strings from an arXiv HTML page.

    Strictly scoped to the affiliation frontmatter (LaTeXML ``ltx_role_affiliation``
    / ``ltx_contact`` spans, plus ``citation_author_institution`` meta tags).
    This keeps false positives low -- a lab name mentioned in the abstract,
    introduction, or references is never treated as an affiliation -- and bounds
    the size of what we keep. Returns short candidate strings to regex-match.
    """

    soup = BeautifulSoup(html, "html.parser")
    chunks: List[str] = []
    seen = set()

    def add(text):
        if not text:
            return
        text = " ".join(text.split())[:MAX_AFFIL_LEN]
        if text and text not in seen:
            seen.add(text)
            chunks.append(text)

    for marker in _AFFIL_CLASSES:
        for el in soup.find_all(class_=_class_match(marker)):
            add(el.get_text(" ", strip=True))

    for meta in soup.find_all(
        "meta", attrs={"name": "citation_author_institution"}
    ):
        add(meta.get("content"))

    return chunks


def _resolve_html(
    client: HttpClient,
    paper: Paper,
    only: Optional[List[str]],
) -> Resolution:
    url = "https://arxiv.org/html/" + (paper.arxiv_id or "")
    html = client.get_text(url)
    if not html:
        return Resolution(resolved_via="unresolved")
    chunks = parse_html_affiliations(html)
    by_affil = config.match_labs_by_affiliation(chunks, only=only)
    if not by_affil:
        return Resolution(resolved_via="unresolved")
    labs = sorted(by_affil.keys())
    evidence: List[str] = []
    for ev in by_affil.values():
        evidence.extend(ev)
    return Resolution(labs=labs, evidence=evidence, resolved_via="html")


def resolve(
    client: HttpClient,
    papers: List[Paper],
    mailto: Optional[str] = None,
    fetch_html: bool = True,
    concurrency: int = 6,
    cache: Optional[Cache] = None,
    only: Optional[List[str]] = None,
) -> Dict[str, Resolution]:
    """Resolve labs/authors for each arXiv candidate paper.

    Returns a dict keyed by versionless arXiv id.
    """

    cache = cache or Cache(None, enabled=False)
    results: Dict[str, Resolution] = {}
    to_lookup: List[Paper] = []

    # 0) cache hits
    for paper in papers:
        if not paper.arxiv_id:
            continue
        cached = cache.get("affiliation", _cache_key(paper.arxiv_id, only))
        if cached is not None:
            results[paper.arxiv_id] = Resolution.from_cache(cached)
        else:
            to_lookup.append(paper)

    # 1) bulk OpenAlex DOI lookup
    arxiv_dois = {
        p.arxiv_id: "10.48550/arXiv." + p.arxiv_id for p in to_lookup if p.arxiv_id
    }
    works_by_arxiv: Dict[str, Dict] = {}
    if arxiv_dois:
        works = openalex.works_by_dois(client, list(arxiv_dois.values()), mailto)
        for work in works:
            aid = openalex.arxiv_id_from_doi(work.get("doi"))
            if aid:
                works_by_arxiv[aid] = work

    needs_html: List[Paper] = []
    # OpenAlex authors for papers that fall through to the HTML fallback because
    # OpenAlex carried no usable affiliation string. We keep these so an HTML lab
    # match still retains the OpenAlex author ids (prominence + Key People).
    html_fallback_authors: Dict[str, List[PaperAuthor]] = {}
    for paper in to_lookup:
        aid = paper.arxiv_id
        work = works_by_arxiv.get(aid)
        if work is not None:
            labs, evidence, authors = _labs_from_work(work, only)
            # A lab match (collective byline / institution / affiliation) settles
            # the paper even when human authors carry empty affiliations -- this
            # is the DeepSeek-V3.2 shape (collective "DeepSeek-AI", empty human
            # affiliations). Keep the OpenAlex authors so prominence still works.
            if labs:
                res = Resolution(
                    labs=labs,
                    authors=authors,
                    evidence=evidence,
                    resolved_via="openalex",
                )
                results[aid] = res
                cache.set("affiliation", _cache_key(aid, only), res.to_cache())
                continue
            # OpenAlex knows the affiliations and none match a covered lab: the
            # paper is settled (not ours). Only settle here when OpenAlex carries
            # a usable affiliation STRING; bare institution ids with empty/junk
            # raw strings are not enough, so those fall through to HTML.
            if _has_usable_affiliation_strings(authors):
                res = Resolution(authors=authors, resolved_via="openalex")
                results[aid] = res
                cache.set("affiliation", _cache_key(aid, only), res.to_cache())
                continue
            # OpenAlex-present-but-empty-affiliations: remember the authors so the
            # HTML-derived Resolution can keep their ids if HTML finds a lab.
            if authors:
                html_fallback_authors[aid] = authors
        # Not resolved by OpenAlex (absent, or present with empty/unusable
        # affiliations) -> candidate for the arxiv.org/html affiliation fallback.
        needs_html.append(paper)

    # 2) HTML fallback (only when enabled)
    if fetch_html and needs_html:
        def work(paper: Paper) -> "tuple[str, Resolution]":
            try:
                res = _resolve_html(client, paper, only)
            except Exception:
                # An unresolved paper is skipped, not fatal.
                res = Resolution(resolved_via="unresolved")
            # Attach the OpenAlex authors carried alongside the fallback so the
            # paper keeps its author ids / prominence even when resolved by HTML.
            oa_authors = html_fallback_authors.get(paper.arxiv_id)
            if oa_authors and not res.authors:
                res.authors = oa_authors
            return paper.arxiv_id, res

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for aid, res in pool.map(work, needs_html):
                results[aid] = res
                cache.set("affiliation", _cache_key(aid, only), res.to_cache())
    else:
        for paper in needs_html:
            res = Resolution(resolved_via="unresolved")
            results[paper.arxiv_id] = res
            # do not cache unresolved-without-html: a later --fulltext run
            # should still get a chance to resolve via HTML.

    return results
