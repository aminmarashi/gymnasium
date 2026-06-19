"""Watchlist institution engine: resolve NL research-node labels to OpenAlex
institution ids and fetch their recent in-window GenAI works.

Reuses the same OpenAlex institution-works engine the six labs use, plus the
structured GenAI topic filter. Resolutions are cached by search term and
per-entry failures degrade to an 'unresolved' marker rather than aborting.
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

# Bump to invalidate stale cached resolutions when the resolver semantics change.
# v2: NL-only resolution (country_code=NL); no fallback to a global/foreign org.
# v3: never-cache empty/error results; invalidates stale v2 ``{}`` misses that a
#     prior transient failure wrote and that could keep a node unresolved.
_INSTITUTION_CACHE_VERSION = "v3"

# Marker for a node with no distinct NL OpenAlex institution: its papers are
# covered via the people list, so its institution-wide pull is skipped.
PEOPLE_TRACKED = "people-tracked"


@dataclass
class ResolvedInstitution:
    """A tracked NL research node: configured label + the resolved OpenAlex
    institution and its in-window GenAI papers (attached later, from the pool).

    ``status`` is ``resolved`` (a distinct NL OpenAlex institution, paper-pulled),
    ``people-tracked`` (no distinct NL institution -- covered via the people list,
    NO institution-wide pull), or ``unresolved``.
    """

    label: str
    search_term: str
    status: str = "unresolved"  # resolved | people-tracked | unresolved
    openalex_id: Optional[str] = None
    display_name: Optional[str] = None
    note: str = ""
    papers: List[Paper] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "search_term": self.search_term,
            "status": self.status,
            "openalex_id": self.openalex_id,
            "display_name": self.display_name,
            "note": self.note,
            "papers": [
                {
                    "title": p.title,
                    "date": p.date,
                    "link": p.abs_url or p.doi_url or p.source_url,
                    "signal": p.impact_summary(),
                }
                for p in self.papers
            ],
        }


_NO_NL_NOTE = "tracked via people (no distinct NL OpenAlex institution)"


def resolve_institutions(
    client: HttpClient,
    institutions: List[Dict[str, Any]],
    mailto: Optional[str] = None,
    cache: Optional[Cache] = None,
) -> List[ResolvedInstitution]:
    """Resolve each NL node to an NL-SPECIFIC OpenAlex institution.

    Resolution is constrained to ``country_code=NL`` so a node never resolves to
    a global/foreign org of the same name. A node explicitly flagged
    ``people_tracked`` is marked ``people-tracked`` and its institution-wide
    paper pull is skipped -- its work is covered via the people list. An unflagged
    node whose NL search errors or returns no NL match degrades to ``unresolved``
    (non-fatal): it is NOT relabelled as people-tracked, and the transient/empty
    failure is NOT cached, so a later run can still resolve it. A vetted
    ``openalex_id`` in the config is honoured directly. Only genuine successful
    resolutions are cached, keyed by versioned search term.
    """

    cache = cache or Cache(None, enabled=False)
    out: List[ResolvedInstitution] = []
    for entry in institutions:
        label = entry.get("label") or ""
        term = entry.get("search_term") or ""
        ri = ResolvedInstitution(label=label, search_term=term)

        # Explicitly people-tracked: never pull institution-wide papers.
        if entry.get("people_tracked"):
            ri.status = PEOPLE_TRACKED
            ri.note = entry.get("note") or _NO_NL_NOTE
            out.append(ri)
            continue

        # Vetted NL id pinned in config: trust it, no search needed.
        if entry.get("openalex_id"):
            ri.status = "resolved"
            ri.openalex_id = openalex.short_id(entry.get("openalex_id"))
            ri.display_name = entry.get("display_name") or label
            out.append(ri)
            continue

        key = _INSTITUTION_CACHE_VERSION + "|" + term.strip().lower()
        data = cache.get("watchlist_institution", key)
        # Treat any empty/falsy cached value (e.g. a stale ``{}`` written by an
        # older resolver) as a cache MISS, so it is re-resolved rather than left
        # permanently unresolved.
        if not data:
            try:
                records = openalex.institutions_search(
                    client, term, mailto, country_code="nl"
                )
            except Exception:
                records = []
            data = {}
            if records:
                top = records[0]  # NL-constrained, highest works_count
                data = {
                    "openalex_id": openalex.short_id(top.get("id")),
                    "display_name": top.get("display_name"),
                }
                # Cache ONLY a genuine successful resolution. A search error or
                # an empty NL result is transient and left uncached so a later
                # run can still resolve the node.
                cache.set("watchlist_institution", key, data)

        if data and data.get("openalex_id"):
            ri.status = "resolved"
            ri.openalex_id = data.get("openalex_id")
            ri.display_name = data.get("display_name")
        else:
            # Search errored or returned no NL match. Do NOT fall back to the
            # global org, and do NOT relabel as people-tracked (only explicitly
            # configured people_tracked entries get that). Degrade to a
            # non-fatal 'unresolved' marker; the transient failure stays
            # uncached (above) so a later run can resolve it.
            ri.status = "unresolved"
        out.append(ri)
    return out


def institution_works(
    client: HttpClient,
    label: str,
    institution_id: str,
    from_date: str,
    to_date: str,
    mailto: Optional[str] = None,
    require_keyword: bool = True,
    max_pages: int = 10,
) -> List[Paper]:
    """In-window GenAI papers at one resolved institution, tagged for ``label``.

    Uses the shared OpenAlex institution-works engine, tags
    ``watchlist_institution=[label]``, and applies the STRICT GenAI filter.
    """

    if not institution_id:
        return []
    try:
        works = openalex.works_by_institutions(
            client, [institution_id], from_date, to_date, mailto,
            max_pages=max_pages,
        )
    except Exception:
        return []
    out: List[Paper] = []
    for work in works:
        paper = openalex.normalize_work(work)
        paper.source_engines = ["watchlist-institutions"]
        paper.watchlist_institution = [label]
        paper.resolved_via = "openalex"
        # Institution-wide scans add a positive CS-field gate on top of the
        # shared GenAI topic filter: a university spans every field, so soft-
        # science papers that merely mention an LLM must be dropped. The filter
        # is bypassed entirely when require_keyword is off (the escape hatch).
        if not topic_filter(paper, require_keyword):
            continue
        if require_keyword and not config.work_in_cs_field(paper):
            continue
        out.append(paper)
    return out
