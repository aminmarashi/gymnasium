"""Orchestration: run the configured sources, union/dedup, score, sort.

Sourcing is source-agnostic: ``run`` asks each configured ``LabSource`` for
lab-tagged papers, unions and dedups them, then runs the shared prominence +
scoring + report over the result. The pure helpers here (dedup_papers,
attach_prominence) are kept free of network calls so they can be unit-tested
directly from fixtures. ``topic_filter`` is re-exported from ``sources.base``.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config, watchlist as watchlist_config
from .cache import Cache
from .http import HttpClient
from .model import Author, Paper, compute_impact, normalize_title, sort_papers
from .sources import authors, watchlist_institutions, watchlist_people
from .sources.anthropic_site import AnthropicSiteSource
from .sources.arxiv_source import ArxivAffiliationSource
from .sources.base import FetchContext, LabSource, topic_filter
from .sources.openalex_source import OpenAlexInstitutionSource
from .sources.watchlist_institutions import ResolvedInstitution
from .sources.watchlist_people import ResolvedPerson

# Named source registry: maps the names in config.SOURCES to implementations.
SOURCE_CLASSES = {
    OpenAlexInstitutionSource.name: OpenAlexInstitutionSource,
    ArxivAffiliationSource.name: ArxivAffiliationSource,
    AnthropicSiteSource.name: AnthropicSiteSource,
}

# Deterministic order sources run in (and therefore the union/dedup precedence).
_SOURCE_ORDER = [
    OpenAlexInstitutionSource.name,
    ArxivAffiliationSource.name,
    AnthropicSiteSource.name,
]


@dataclass
class Options:
    days: int = 7
    labs: List[str] = field(default_factory=lambda: list(config.LABS.keys()))
    categories: List[str] = field(default_factory=lambda: list(config.DEFAULT_CATEGORIES))
    out_dir: str = "reports"
    fmt: str = "both"  # md | json | both
    concurrency: int = 6
    cache_dir: Optional[str] = "data/cache"
    mailto: Optional[str] = None
    fulltext: bool = True
    max_pages: int = 10
    top_people: int = 25
    giant_cited_by: int = config.GIANT_CITED_BY
    giant_hindex: int = config.GIANT_HINDEX
    require_keyword: bool = True
    arxiv_delay: float = 3.0
    openalex_interval: float = 0.12
    watchlist: bool = True  # include the Netherlands GenAI map / watchlist
    today: Optional[_dt.date] = None  # injectable for tests / reproducibility


@dataclass
class Watchlist:
    """The Netherlands GenAI map: tracked people, NL institutions, and the
    curated companies reference appendix."""

    people: List[ResolvedPerson] = field(default_factory=list)
    people_abroad: List[ResolvedPerson] = field(default_factory=list)
    institutions: List[ResolvedInstitution] = field(default_factory=list)
    companies: List[dict] = field(default_factory=list)
    exclusions_note: str = ""


@dataclass
class Result:
    papers: List[Paper]
    people_overall: List[Author]
    people_by_lab: "Dict[str, List[Author]]"
    from_date: str
    to_date: str
    labs: List[str]
    per_lab_counts: "Dict[str, int]"
    giant_cited_by: int = config.GIANT_CITED_BY
    giant_hindex: int = config.GIANT_HINDEX
    watchlist: Optional[Watchlist] = None


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------
# topic_filter is imported from sources.base and re-exported here for callers /
# tests that reference pipeline.topic_filter.
__all__ = ["topic_filter", "dedup_papers", "attach_prominence", "run",
           "Options", "Result", "Watchlist", "papers_for_lab"]


def _merge_authors(into: Paper, extra: List) -> None:
    by_id: Dict[str, int] = {}
    by_name: Dict[str, int] = {}
    for idx, a in enumerate(into.authors):
        if a.openalex_id:
            by_id[a.openalex_id] = idx
        by_name.setdefault(a.name.lower(), idx)
    for a in extra:
        if a.openalex_id and a.openalex_id in by_id:
            target = into.authors[by_id[a.openalex_id]]
            # prefer the entry that carries affiliation/institution detail
            if not target.institution_ids and a.institution_ids:
                target.institution_ids = a.institution_ids
            if not target.raw_affiliation_strings and a.raw_affiliation_strings:
                target.raw_affiliation_strings = a.raw_affiliation_strings
            continue
        if not a.openalex_id and a.name.lower() in by_name:
            idx = by_name[a.name.lower()]
            target = into.authors[idx]
            if not target.openalex_id and a.openalex_id:
                target.openalex_id = a.openalex_id
            continue
        into.authors.append(a)
        if a.openalex_id:
            by_id[a.openalex_id] = len(into.authors) - 1
        by_name.setdefault(a.name.lower(), len(into.authors) - 1)


def _merge_into(into: Paper, other: Paper) -> None:
    for lab in other.labs_matched:
        if lab not in into.labs_matched:
            into.labs_matched.append(lab)
    for nm in other.watchlist_people:
        if nm not in into.watchlist_people:
            into.watchlist_people.append(nm)
    for label in other.watchlist_institution:
        if label not in into.watchlist_institution:
            into.watchlist_institution.append(label)
    for eng in other.source_engines:
        if eng not in into.source_engines:
            into.source_engines.append(eng)
    for ev in other.affiliation_evidence:
        if ev not in into.affiliation_evidence:
            into.affiliation_evidence.append(ev)
    for cat in other.categories:
        if cat not in into.categories:
            into.categories.append(cat)
    into.cited_by_count = max(into.cited_by_count, other.cited_by_count)
    if not into.abstract and other.abstract:
        into.abstract = other.abstract
    if not into.date and other.date:
        into.date = other.date
    if not into.doi and other.doi:
        into.doi = other.doi
    if not into.primary_category and other.primary_category:
        into.primary_category = other.primary_category
    # Carry the OpenAlex structured topic signal through dedup (an OpenAlex
    # record merged into an arXiv-first one would otherwise lose its topic data).
    if not into.primary_topic and other.primary_topic:
        into.primary_topic = other.primary_topic
    if not into.primary_field and other.primary_field:
        into.primary_field = other.primary_field
    if not into.primary_subfield and other.primary_subfield:
        into.primary_subfield = other.primary_subfield
    for tf in other.topic_fields:
        if tf not in into.topic_fields:
            into.topic_fields.append(tf)
    for attr in ("abs_url", "pdf_url", "doi_url", "source_url"):
        if not getattr(into, attr) and getattr(other, attr):
            setattr(into, attr, getattr(other, attr))
    if other.resolved_via and other.resolved_via != "unresolved" and (
        not into.resolved_via or into.resolved_via == "unresolved"
    ):
        into.resolved_via = other.resolved_via
    _merge_authors(into, other.authors)


def dedup_papers(papers: List[Paper]) -> List[Paper]:
    """Union/dedup when ANY identity matches.

    Two papers are the same when they share a versionless arXiv id, DOI, source
    url, OR normalized title (see Paper.identity_keys). Source url is an
    additional identity, never a replacement for title dedup, so OpenAlex/site
    duplicates with different urls but the same title still merge.
    """

    canonical: "Dict[str, Paper]" = {}  # identity key -> canonical paper
    order: List[Paper] = []
    superseded: set = set()  # ids of canonical papers folded into another
    for paper in papers:
        keys = paper.identity_keys()
        # Collect EVERY canonical record this paper touches. A paper can bridge
        # several (e.g. its DOI matches one record, its title another); merging
        # only the first would leave the rest as duplicates, so dedup must be
        # transitive -- fold them all into one.
        targets: List[Paper] = []
        seen_targets: set = set()
        for key in keys:
            t = canonical.get(key)
            if t is not None and id(t) not in seen_targets:
                seen_targets.add(id(t))
                targets.append(t)
        if not targets:
            order.append(paper)
            for key in keys:
                canonical.setdefault(key, paper)
            continue
        primary = targets[0]
        extras = targets[1:]
        for extra in extras:
            _merge_into(primary, extra)
            superseded.add(id(extra))
        _merge_into(primary, paper)
        # Repoint every key that referenced a folded record to the survivor, then
        # register all identities of the paper and the survivor, so a later
        # duplicate matching on any of them collapses here too.
        if extras:
            extra_ids = {id(e) for e in extras}
            for key, val in list(canonical.items()):
                if id(val) in extra_ids:
                    canonical[key] = primary
        for key in keys + primary.identity_keys():
            canonical[key] = primary
    if superseded:
        order = [p for p in order if id(p) not in superseded]
    return order


def papers_for_lab(papers: List[Paper], lab_key: str) -> List[Paper]:
    """Papers matched to a lab, de-duped by normalized title within the section.

    A paper can appear under several arXiv ids/DOIs (e.g. crossposts); dedup by
    arXiv id/DOI alone keeps both. Callers pass papers already sorted by impact,
    so the first (highest-signal) occurrence of each title is the one kept.
    """

    out: List[Paper] = []
    seen: set = set()
    for p in papers:
        if lab_key not in p.labs_matched:
            continue
        key = normalize_title(p.title)
        if key and key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def attach_prominence(
    papers: List[Paper],
    prominence_map: "Dict[str, Author]",
    giant_cited_by: int = config.GIANT_CITED_BY,
    giant_hindex: int = config.GIANT_HINDEX,
) -> List[Paper]:
    """Enrich author refs, compute impact fields, and sort by signal."""

    for paper in papers:
        authors.enrich_paper_authors(
            paper.authors, prominence_map, giant_cited_by, giant_hindex
        )
        compute_impact(paper, giant_cited_by, giant_hindex)
    return sort_papers(papers)


# --------------------------------------------------------------------------
# Live orchestration
# --------------------------------------------------------------------------
def _date_window(opts: Options) -> "tuple[str, str]":
    today = opts.today or _dt.date.today()
    frm = today - _dt.timedelta(days=opts.days)
    return frm.isoformat(), today.isoformat()


def build_sources(lab_keys: List[str]) -> "List[LabSource]":
    """Instantiate, in deterministic order, the sources covering these labs."""

    wanted = set(config.sources_for_labs(lab_keys))
    ordered = [n for n in _SOURCE_ORDER if n in wanted]
    ordered += [n for n in wanted if n not in _SOURCE_ORDER]
    return [SOURCE_CLASSES[n]() for n in ordered if n in SOURCE_CLASSES]


def _resolve_site_author_ids(all_papers: List[Paper], ctx: FetchContext) -> None:
    """Best-effort: attach OpenAlex ids to site-paper authors known only by name.

    Site sources (e.g. Anthropic) give author NAMES but no OpenAlex ids. We
    resolve those names to ids so the shared prominence step picks them up and
    the papers participate in signal-sorting / Key People. Names with no
    confident AI/CS match are left without an id (prominence stays unavailable).
    """

    names: set = set()
    for p in all_papers:
        if "anthropic-site" not in p.source_engines:
            continue
        for a in p.authors:
            if a.name and not a.openalex_id:
                names.add(a.name)
    if not names:
        return
    name_map = authors.authors_by_name(
        ctx.client, sorted(names), mailto=ctx.mailto, cache=ctx.cache
    )
    for p in all_papers:
        if "anthropic-site" not in p.source_engines:
            continue
        for a in p.authors:
            if a.openalex_id:
                continue
            match = name_map.get(authors._normalize_name(a.name))
            if match and match.openalex_id:
                a.openalex_id = match.openalex_id


def _collect_watchlist(
    opts: Options,
    from_date: str,
    to_date: str,
    client: HttpClient,
    cache: Cache,
) -> "tuple[List[ResolvedPerson], List[ResolvedPerson], List[ResolvedInstitution], List[Paper]]":
    """Resolve watchlist people + institutions and fetch their in-window GenAI
    papers. Returns (NL people, abroad people, institutions, collected papers).

    Every lookup is best-effort: a failed person/institution simply stays
    unresolved (or paperless) and never aborts the run.
    """

    people = watchlist_people.resolve_people(
        client, watchlist_config.WATCHLIST_PEOPLE, mailto=opts.mailto,
        cache=cache, giant_cited_by=opts.giant_cited_by,
        giant_hindex=opts.giant_hindex,
    )
    people_abroad = watchlist_people.resolve_people(
        client, watchlist_config.WATCHLIST_PEOPLE_ABROAD, mailto=opts.mailto,
        cache=cache, giant_cited_by=opts.giant_cited_by,
        giant_hindex=opts.giant_hindex,
    )
    institutions = watchlist_institutions.resolve_institutions(
        client, watchlist_config.WATCHLIST_INSTITUTIONS, mailto=opts.mailto,
        cache=cache,
    )

    collected: List[Paper] = []
    for person in people + people_abroad:
        if person.status != "resolved" or not person.openalex_id:
            continue
        collected.extend(watchlist_people.recent_works(
            client, person.openalex_id, person.name, from_date, to_date,
            mailto=opts.mailto, require_keyword=opts.require_keyword,
            max_pages=opts.max_pages,
        ))
    for inst in institutions:
        if inst.status != "resolved" or not inst.openalex_id:
            continue
        collected.extend(watchlist_institutions.institution_works(
            client, inst.label, inst.openalex_id, from_date, to_date,
            mailto=opts.mailto, require_keyword=opts.require_keyword,
            max_pages=opts.max_pages,
        ))
    return people, people_abroad, institutions, collected


def _attach_watchlist_papers(
    all_papers: List[Paper],
    people: List[ResolvedPerson],
    institutions: List[ResolvedInstitution],
) -> None:
    """Attach each watchlist entry's in-window papers from the deduped, sorted
    pool (so a paper that also belongs to a lab carries both tags and is shown
    once, signal-sorted)."""

    for person in people:
        person.papers = [
            p for p in all_papers if person.name in p.watchlist_people
        ]
    for inst in institutions:
        inst.papers = [
            p for p in all_papers if inst.label in p.watchlist_institution
        ]


def run(opts: Options, client: Optional[HttpClient] = None) -> Result:
    from_date, to_date = _date_window(opts)
    labs = config.selected_labs(opts.labs)
    lab_keys = list(labs.keys())

    client = client or HttpClient(
        mailto=opts.mailto, min_interval=opts.openalex_interval
    )
    cache = Cache(opts.cache_dir, enabled=bool(opts.cache_dir))

    ctx = FetchContext(
        from_date=from_date,
        to_date=to_date,
        lab_keys=lab_keys,
        client=client,
        cache=cache,
        mailto=opts.mailto,
        categories=opts.categories,
        require_keyword=opts.require_keyword,
        fulltext=opts.fulltext,
        concurrency=opts.concurrency,
        max_pages=opts.max_pages,
        arxiv_delay=opts.arxiv_delay,
    )

    # --- Sourcing: union of every configured source's lab-tagged papers ------
    collected: List[Paper] = []
    for source in build_sources(lab_keys):
        try:
            collected.extend(source.fetch(ctx))
        except Exception:
            # A single source failing degrades coverage, never the whole run.
            continue

    # --- Watchlist: NL GenAI map (people + institutions), same pool ----------
    wl_people: List[ResolvedPerson] = []
    wl_people_abroad: List[ResolvedPerson] = []
    wl_institutions: List[ResolvedInstitution] = []
    if opts.watchlist:
        try:
            (wl_people, wl_people_abroad, wl_institutions,
             wl_papers) = _collect_watchlist(
                opts, from_date, to_date, client, cache
            )
            collected.extend(wl_papers)
        except Exception:
            # Watchlist is additive: any failure degrades it, never the run.
            wl_people, wl_people_abroad, wl_institutions = [], [], []

    # --- Union + dedup ------------------------------------------------------
    all_papers = dedup_papers(collected)

    # Site papers have author names but no OpenAlex ids: resolve them so the
    # shared prominence step can score them like everything else.
    _resolve_site_author_ids(all_papers, ctx)

    # --- Prominence (shared engine) -----------------------------------------
    author_ids: List[str] = []
    for paper in all_papers:
        for a in paper.authors:
            if a.openalex_id:
                author_ids.append(a.openalex_id)
    prominence_map = authors.prominence(
        client,
        author_ids,
        mailto=opts.mailto,
        cache=cache,
        giant_cited_by=opts.giant_cited_by,
        giant_hindex=opts.giant_hindex,
    )
    all_papers = attach_prominence(
        all_papers, prominence_map, opts.giant_cited_by, opts.giant_hindex
    )

    # --- Key People ---------------------------------------------------------
    people_by_lab: "Dict[str, List[Author]]" = {}
    for key, lab in labs.items():
        if lab.openalex_institution_ids:
            people_by_lab[key] = authors.top_people_by_institution(
                client,
                lab,
                mailto=opts.mailto,
                n=opts.top_people,
                giant_cited_by=opts.giant_cited_by,
                giant_hindex=opts.giant_hindex,
            )
        else:
            people_by_lab[key] = authors.rank_authors_from_papers(
                key, all_papers, prominence_map, n=opts.top_people
            )
    people_overall = authors.merge_overall(people_by_lab, n=opts.top_people)

    per_lab_counts = {
        key: len(papers_for_lab(all_papers, key)) for key in lab_keys
    }

    watchlist: Optional[Watchlist] = None
    if opts.watchlist:
        _attach_watchlist_papers(
            all_papers, wl_people + wl_people_abroad, wl_institutions
        )
        watchlist = Watchlist(
            people=wl_people,
            people_abroad=wl_people_abroad,
            institutions=wl_institutions,
            companies=watchlist_config.REFERENCE_COMPANIES,
            exclusions_note=watchlist_config.EXCLUSIONS_NOTE,
        )

    return Result(
        papers=all_papers,
        people_overall=people_overall,
        people_by_lab=people_by_lab,
        from_date=from_date,
        to_date=to_date,
        labs=lab_keys,
        per_lab_counts=per_lab_counts,
        giant_cited_by=opts.giant_cited_by,
        giant_hindex=opts.giant_hindex,
        watchlist=watchlist,
    )
