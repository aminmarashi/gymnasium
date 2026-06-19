"""Watchlist people engine: resolve named researchers to OpenAlex profiles and
fetch their recent in-window GenAI works.

Reuses the existing OpenAlex author-search / works engine, the structured GenAI
topic filter, and (downstream, via the shared pipeline) the prominence step.
Per-entry failures degrade to an 'unresolved' marker rather than aborting the
run; resolutions are cached by name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import config
from ..cache import Cache
from ..http import HttpClient
from ..model import Paper
from . import openalex
from .base import topic_filter

# A resolved candidate must clear this works_count bar to be plausible -- it
# drops thin / junk OpenAlex author stubs that share a common name.
MIN_WORKS_COUNT = 5

# An NL-affiliated profile is preferred over a higher-cited foreign namesake
# (the local researcher is the intended target), but ONLY when the foreign
# candidate is not OVERWHELMINGLY more prominent. This guard stops a thin local
# namesake stub from displacing a clearly-correct, far-more-cited profile that
# simply is not NL-tagged in OpenAlex (e.g. Max Welling, whose top profile lists
# no last-known institution). A non-NL candidate wins only when it out-cites the
# best NL candidate by more than this factor.
NL_PREFER_MAX_RATIO = 10

# Bump to invalidate stale cached resolutions when the resolver semantics change.
# v3: NL-affiliation preference (guarded against displacing an overwhelmingly
# more-prominent non-NL profile) + below-threshold-only candidates stay
# unresolved.
_PERSON_CACHE_VERSION = "v3"


@dataclass
class ResolvedPerson:
    """A tracked person: configured metadata + the resolved OpenAlex profile and
    its in-window GenAI papers (attached later, from the deduped pool)."""

    name: str
    note: str = ""
    verify: bool = False
    abroad: bool = False
    status: str = "unresolved"  # resolved | unresolved
    openalex_id: Optional[str] = None
    display_name: Optional[str] = None
    last_institution_name: Optional[str] = None
    cited_by_count: int = 0
    h_index: int = 0
    works_count: int = 0
    is_giant: bool = False
    papers: List[Paper] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "note": self.note,
            "verify": self.verify,
            "abroad": self.abroad,
            "status": self.status,
            "openalex_id": self.openalex_id,
            "display_name": self.display_name,
            "last_institution_name": self.last_institution_name,
            "cited_by_count": self.cited_by_count,
            "h_index": self.h_index,
            "works_count": self.works_count,
            "is_giant": self.is_giant,
            "papers": [_paper_brief(p) for p in self.papers],
        }


def _paper_brief(p: Paper) -> Dict[str, Any]:
    """Compact paper summary for the watchlist JSON (the full record lives in the
    top-level ``papers`` array; this avoids duplicating it wholesale)."""

    return {
        "title": p.title,
        "date": p.date,
        "arxiv_id": p.arxiv_id,
        "doi": p.doi,
        "link": p.abs_url or p.doi_url or p.source_url,
        "signal": p.impact_summary(),
    }


def _institution_records(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    insts = record.get("last_known_institutions") or []
    if insts:
        return [i for i in insts if i]
    inst = record.get("last_known_institution")
    return [inst] if inst else []


def _last_institution_name(record: Dict[str, Any]) -> Optional[str]:
    insts = _institution_records(record)
    return insts[0].get("display_name") if insts else None


def _is_nl_affiliated(record: Dict[str, Any]) -> bool:
    """Whether the author's last-known institution is in the Netherlands.

    Checks the OpenAlex ``country_code`` first, then a display-name fallback
    ("Netherlands"/"Amsterdam") for records that omit the code. Used to surface
    the NL-based researcher over a higher-cited foreign namesake.
    """

    for inst in _institution_records(record):
        if (inst.get("country_code") or "").strip().upper() == "NL":
            return True
        name = (inst.get("display_name") or "").lower()
        if "netherlands" in name or "amsterdam" in name:
            return True
    return False


def _best_person_candidate(
    records: List[Dict[str, Any]], min_works: int = MIN_WORKS_COUNT
) -> Optional[Dict[str, Any]]:
    """Pick the best AI/CS author from a name search.

    ``records`` arrive sorted by citation count (see ``openalex.authors_search``).
    We require an AI/CS topical profile -- so a higher-cited non-CS namesake is
    skipped -- and only consider candidates that clear the works_count
    plausibility bar. Among those, an NL-affiliated profile is preferred (these
    are NL-based researchers, so an NL affiliation disambiguates a buried local
    profile from a higher-cited foreign namesake); otherwise the first
    threshold-clearing AI/CS candidate wins.

    Returns None when no AI/CS candidate clears the bar -- a below-threshold-only
    match is ambiguous/junk and stays UNRESOLVED rather than being picked.
    """

    plausible: List[Dict[str, Any]] = []
    for r in records:
        if not openalex.author_is_cs_ai(r):
            continue
        if int(r.get("works_count") or 0) >= min_works:
            plausible.append(r)
    if not plausible:
        return None

    def _cited(r: Dict[str, Any]) -> int:
        return int(r.get("cited_by_count") or 0)

    best_overall = max(plausible, key=_cited)
    nl = [r for r in plausible if _is_nl_affiliated(r)]
    if nl:
        best_nl = max(nl, key=_cited)
        # Prefer the NL profile unless a non-NL candidate is overwhelmingly more
        # prominent (then it is the real target that just is not NL-tagged).
        if best_nl is best_overall or (
            _cited(best_nl) * NL_PREFER_MAX_RATIO >= _cited(best_overall)
        ):
            return best_nl
    return best_overall


def _merge_records(
    primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Concatenate two author-record lists, de-duplicated by OpenAlex id,
    keeping ``primary`` order first."""

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for r in list(primary) + list(secondary):
        rid = r.get("id")
        if rid in seen:
            continue
        seen.add(rid)
        out.append(r)
    return out


def resolve_people(
    client: HttpClient,
    people: List[Dict[str, Any]],
    mailto: Optional[str] = None,
    cache: Optional[Cache] = None,
    giant_cited_by: int = config.GIANT_CITED_BY,
    giant_hindex: int = config.GIANT_HINDEX,
) -> List[ResolvedPerson]:
    """Resolve each configured person to an OpenAlex profile (cached by name).

    Records the chosen id + display_name + last-known institution so the report
    shows exactly what was picked; ambiguous / non-CS names stay 'unresolved'.
    """

    cache = cache or Cache(None, enabled=False)
    out: List[ResolvedPerson] = []
    for entry in people:
        name = entry.get("name") or ""
        rp = ResolvedPerson(
            name=name,
            note=entry.get("note", ""),
            verify=bool(entry.get("verify")),
            abroad=bool(entry.get("abroad")),
        )
        key = _PERSON_CACHE_VERSION + "|" + name.strip().lower()
        data = cache.get("watchlist_person", key)
        if data is None:
            try:
                records = openalex.authors_search(client, name, mailto)
            except Exception:
                records = []
            # Also pull NL-affiliated namesakes: the local researcher is often
            # buried under higher-cited foreign namesakes and never surfaces in
            # the citation-sorted global search (e.g. the UvA NLP "Raquel
            # Fernandez" vs. a medical namesake). Merge by id, NL records first
            # so the preference is honoured even on ties.
            try:
                nl_records = openalex.authors_search(
                    client, name, mailto, country_code="nl"
                )
            except Exception:
                nl_records = []
            records = _merge_records(nl_records, records)
            match = _best_person_candidate(records)
            data = {}
            if match:
                stats = match.get("summary_stats") or {}
                data = {
                    "openalex_id": openalex.short_id(match.get("id")),
                    "display_name": match.get("display_name"),
                    "last_institution_name": _last_institution_name(match),
                    "cited_by_count": int(match.get("cited_by_count") or 0),
                    "h_index": int(stats.get("h_index") or 0),
                    "works_count": int(match.get("works_count") or 0),
                }
            cache.set("watchlist_person", key, data)

        if data and data.get("openalex_id"):
            rp.status = "resolved"
            rp.openalex_id = data.get("openalex_id")
            rp.display_name = data.get("display_name")
            rp.last_institution_name = data.get("last_institution_name")
            rp.cited_by_count = int(data.get("cited_by_count") or 0)
            rp.h_index = int(data.get("h_index") or 0)
            rp.works_count = int(data.get("works_count") or 0)
            rp.is_giant = (
                rp.cited_by_count >= giant_cited_by or rp.h_index >= giant_hindex
            )
        out.append(rp)
    return out


def recent_works(
    client: HttpClient,
    author_id: str,
    name: str,
    from_date: str,
    to_date: str,
    mailto: Optional[str] = None,
    require_keyword: bool = True,
    max_pages: int = 10,
) -> List[Paper]:
    """In-window GenAI papers for one resolved author id, tagged for ``name``.

    Normalizes each OpenAlex work, tags ``watchlist_people=[name]``, and applies
    the STRICT GenAI structured topic filter so non-GenAI works are dropped.
    """

    if not author_id:
        return []
    try:
        works = openalex.works_by_author(
            client, author_id, from_date, to_date, mailto, max_pages=max_pages
        )
    except Exception:
        return []
    out: List[Paper] = []
    for work in works:
        paper = openalex.normalize_work(work)
        paper.source_engines = ["watchlist-people"]
        paper.watchlist_people = [name]
        paper.resolved_via = "openalex"
        if topic_filter(paper, require_keyword):
            out.append(paper)
    return out
