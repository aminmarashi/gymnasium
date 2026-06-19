"""Author-prominence engine -- the single source of "giant-weight".

The same prominence data powers BOTH the per-paper impact signal and the Key
People ranking: we look up authors once and reuse the numbers everywhere.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .. import config
from ..cache import Cache
from ..http import HttpClient
from ..model import Author
from . import openalex


def _h_index(record: Dict) -> int:
    stats = record.get("summary_stats") or {}
    return int(stats.get("h_index") or 0)


def _last_institution_name(record: Dict) -> Optional[str]:
    insts = record.get("last_known_institutions") or []
    if insts:
        return insts[0].get("display_name")
    inst = record.get("last_known_institution")
    if inst:
        return inst.get("display_name")
    return None


def _is_giant(cited_by: int, h_index: int, giant_cited_by: int, giant_hindex: int) -> bool:
    return cited_by >= giant_cited_by or h_index >= giant_hindex


def _author_from_cache(d: Dict, giant_cited_by: int, giant_hindex: int) -> Optional[Author]:
    """Rebuild an Author from cached *raw* stats, recomputing is_giant.

    The cache stores only raw stats so a run with custom --giant thresholds is
    never served a stale is_giant from whatever thresholds populated the cache.
    """

    if not isinstance(d, dict):
        return None
    cited = int(d.get("cited_by_count") or 0)
    h = int(d.get("h_index") or 0)
    return Author(
        openalex_id=d.get("openalex_id") or "",
        name=d.get("name") or "",
        cited_by_count=cited,
        h_index=h,
        works_count=int(d.get("works_count") or 0),
        last_institution_name=d.get("last_institution_name"),
        lab=d.get("lab"),
        is_giant=_is_giant(cited, h, giant_cited_by, giant_hindex),
        is_cs=bool(d.get("is_cs", True)),
    )


def prominence(
    client: HttpClient,
    author_ids: List[str],
    mailto: Optional[str] = None,
    cache: Optional[Cache] = None,
    giant_cited_by: int = config.GIANT_CITED_BY,
    giant_hindex: int = config.GIANT_HINDEX,
) -> Dict[str, Author]:
    """Look up prominence for the given OpenAlex author ids (batched, cached)."""

    cache = cache or Cache(None, enabled=False)
    ids = sorted({openalex.short_id(a) for a in author_ids if a})
    out: Dict[str, Author] = {}
    missing: List[str] = []
    for aid in ids:
        cached = cache.get("author", aid)
        if cached is not None:
            out[aid] = _author_from_cache(cached, giant_cited_by, giant_hindex)
        else:
            missing.append(aid)

    if missing:
        records = openalex.authors_by_ids(client, missing, mailto)
        for rec in records:
            aid = openalex.short_id(rec.get("id"))
            if not aid:
                continue
            cited = int(rec.get("cited_by_count") or 0)
            h = _h_index(rec)
            author = Author(
                openalex_id=aid,
                name=rec.get("display_name") or "",
                cited_by_count=cited,
                h_index=h,
                works_count=int(rec.get("works_count") or 0),
                last_institution_name=_last_institution_name(rec),
                is_giant=_is_giant(cited, h, giant_cited_by, giant_hindex),
                is_cs=openalex.author_is_cs_ai(rec),
            )
            out[aid] = author
            cache.set("author", aid, author.to_dict())

    # drop any None placeholders from bad cache reads
    return {k: v for k, v in out.items() if v is not None}


def _normalize_name(name: Optional[str]) -> str:
    return " ".join((name or "").split()).lower()


def _best_name_match(name: str, records: List[Dict]) -> Optional[Dict]:
    """Pick the single AI/CS author whose name exactly matches ``name``.

    Returns one record, or None when there is no CS-AI exact-name match or when
    several distinct authors share that name (ambiguous -> skip rather than
    guess). Pure helper so the disambiguation is unit-testable without network.
    """

    target = _normalize_name(name)
    if not target:
        return None
    matches = [
        r for r in records
        if _normalize_name(r.get("display_name")) == target
        and openalex.author_is_cs_ai(r)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def authors_by_name(
    client: HttpClient,
    names: List[str],
    mailto: Optional[str] = None,
    cache: Optional[Cache] = None,
    giant_cited_by: int = config.GIANT_CITED_BY,
    giant_hindex: int = config.GIANT_HINDEX,
) -> Dict[str, Author]:
    """Best-effort prominence for authors known only by name (no OpenAlex id).

    Searches OpenAlex by display name and keeps a confident AI/CS exact-name
    match (skipping ambiguous names). Used to give site-sourced papers (e.g.
    Anthropic) author prominence. Cached by normalized name (including a
    negative cache for names with no confident match). Returns a dict keyed by
    normalized name.
    """

    cache = cache or Cache(None, enabled=False)
    out: Dict[str, Author] = {}
    for name in names:
        key = _normalize_name(name)
        if not key or key in out:
            continue
        cached = cache.get("author_name", key)
        if cached is not None:
            # an empty dict is a negative-cache marker ("searched, no match")
            if cached:
                author = _author_from_cache(cached, giant_cited_by, giant_hindex)
                if author and author.openalex_id:
                    out[key] = author
            continue
        records = openalex.authors_search(client, name, mailto)
        match = _best_name_match(name, records)
        if not match:
            cache.set("author_name", key, {})
            continue
        aid = openalex.short_id(match.get("id"))
        cited = int(match.get("cited_by_count") or 0)
        h = _h_index(match)
        author = Author(
            openalex_id=aid or "",
            name=match.get("display_name") or name,
            cited_by_count=cited,
            h_index=h,
            works_count=int(match.get("works_count") or 0),
            last_institution_name=_last_institution_name(match),
            is_giant=_is_giant(cited, h, giant_cited_by, giant_hindex),
            is_cs=True,
        )
        out[key] = author
        cache.set("author_name", key, author.to_dict())
    return out


def enrich_paper_authors(
    paper_authors,
    prominence_map: Dict[str, Author],
    giant_cited_by: int = config.GIANT_CITED_BY,
    giant_hindex: int = config.GIANT_HINDEX,
) -> None:
    """Copy looked-up prominence onto a paper's author refs, in place."""

    for pa in paper_authors:
        if not pa.openalex_id:
            continue
        prof = prominence_map.get(pa.openalex_id)
        if not prof:
            continue
        pa.cited_by_count = prof.cited_by_count
        pa.h_index = prof.h_index
        pa.works_count = prof.works_count
        pa.last_institution_name = prof.last_institution_name
        pa.prominence_known = True
        pa.is_giant = _is_giant(
            prof.cited_by_count, prof.h_index, giant_cited_by, giant_hindex
        )


def top_people_by_institution(
    client: HttpClient,
    lab: config.LabConfig,
    mailto: Optional[str] = None,
    n: int = 25,
    giant_cited_by: int = config.GIANT_CITED_BY,
    giant_hindex: int = config.GIANT_HINDEX,
) -> List[Author]:
    """Top AI/CS authors for an OpenAlex-covered lab, via last-known-institution.

    OpenAlex mis-tags some non-CS researchers (e.g. medical) to these labs, so we
    over-fetch and keep only authors whose profile is in AI/ML/CS.
    """

    # Over-fetch: the field filter discards the mis-tagged non-CS researchers.
    pool = max(n * 4, 50)
    records = openalex.top_authors_by_institution(
        client, lab.openalex_institution_ids, mailto, n=pool
    )
    out: List[Author] = []
    for rec in records:
        aid = openalex.short_id(rec.get("id"))
        if not aid:
            continue
        if not openalex.author_is_cs_ai(rec):
            continue
        cited = int(rec.get("cited_by_count") or 0)
        h = _h_index(rec)
        out.append(Author(
            openalex_id=aid,
            name=rec.get("display_name") or "",
            cited_by_count=cited,
            h_index=h,
            works_count=int(rec.get("works_count") or 0),
            last_institution_name=_last_institution_name(rec),
            lab=lab.key,
            is_giant=_is_giant(cited, h, giant_cited_by, giant_hindex),
            is_cs=True,
        ))
        if len(out) >= n:
            break
    return out


def rank_authors_from_papers(
    lab_key: str,
    papers,
    prominence_map: Dict[str, Author],
    n: int = 25,
) -> List[Author]:
    """Rank a lab's people from the authors found on its matched papers.

    Used for Anthropic/DeepSeek, which have no usable OpenAlex institution id.
    """

    best: Dict[str, Author] = {}
    for paper in papers:
        if lab_key not in paper.labs_matched:
            continue
        for pa in paper.authors:
            if not pa.openalex_id:
                continue
            if config.is_persona_author(pa.name, pa.raw_affiliation_strings):
                continue
            prof = prominence_map.get(pa.openalex_id)
            if not prof or not prof.is_cs:
                continue
            author = Author(
                openalex_id=prof.openalex_id,
                name=prof.name or pa.name,
                cited_by_count=prof.cited_by_count,
                h_index=prof.h_index,
                works_count=prof.works_count,
                last_institution_name=prof.last_institution_name,
                lab=lab_key,
                is_giant=prof.is_giant,
            )
            best[prof.openalex_id] = author
    ranked = sorted(
        best.values(), key=lambda a: (a.cited_by_count, a.h_index), reverse=True
    )
    return ranked[:n]


def merge_overall(per_lab: Dict[str, List[Author]], n: int = 25) -> List[Author]:
    """Merge per-lab people into one overall ranking by pure prominence.

    People are already field-filtered to AI/CS upstream, so the Overall list is
    a straight global sort rather than a per-lab interleave: dedupe everyone
    across labs (keeping the strongest copy of a shared author) and order by
    (cited_by_count, h_index) descending, then take the top N. The per-lab
    sections preserve balance.
    """

    best: Dict[str, Author] = {}
    for authors_list in per_lab.values():
        for a in authors_list:
            cur = best.get(a.openalex_id)
            if cur is None or (a.cited_by_count, a.h_index) > (
                cur.cited_by_count, cur.h_index
            ):
                best[a.openalex_id] = a
    ranked = sorted(
        best.values(), key=lambda a: (a.cited_by_count, a.h_index), reverse=True
    )
    return ranked[:n]
