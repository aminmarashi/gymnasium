"""OpenAlex engine: institution works, DOI enrichment, and author lookups.

OpenAlex is the institution-id workhorse. It cleanly tags works for the labs
that have usable institution ids, lets us enrich arXiv candidates by DOI, and
supplies the author-prominence data (citations, h-index) that powers the whole
"giant-weight" ranking.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import requests

from ..http import HttpClient, HttpError
from ..model import Paper, PaperAuthor

OPENALEX_BASE = "https://api.openalex.org"
WORKS_URL = OPENALEX_BASE + "/works"
AUTHORS_URL = OPENALEX_BASE + "/authors"
INSTITUTIONS_URL = OPENALEX_BASE + "/institutions"

# OpenAlex allows up to 50 OR-values per filter; keep a safe margin.
OR_CHUNK = 40
PER_PAGE = 200

# Fields requested from the OpenAlex /works endpoint. Listed explicitly (rather
# than fetching the full record) so the payload stays small AND so primary_topic
# + topics are always present -- they are the structured signal the GenAI topic
# filter classifies OpenAlex works on. Every field normalize_work reads must be
# listed here or it would come back empty.
WORKS_SELECT = ",".join([
    "id", "doi", "title", "display_name", "publication_date",
    "cited_by_count", "authorships", "abstract_inverted_index",
    "primary_location", "primary_topic", "topics",
])

# A failed OpenAlex batch should degrade the run, not kill it.
_OPENALEX_ERRORS = (HttpError, requests.RequestException)

# OpenAlex profile fields that mark an author as an AI/ML/CS researcher. The
# Key People ranking uses this to drop people OpenAlex mis-tags to a lab
# (e.g. urologists tagged to Meta).
_CS_FIELD_NAMES = {"computer science"}
_AI_SUBFIELD_HINTS = (
    "artificial intelligence", "machine learning", "computer vision",
    "natural language", "computational linguistics", "information retrieval",
    "human-computer interaction", "signal processing",
)
_CS_CONCEPTS = {
    "computer science", "artificial intelligence", "machine learning",
    "deep learning", "natural language processing", "reinforcement learning",
}


def author_is_cs_ai(record: Dict[str, Any], concept_threshold: int = 20) -> bool:
    """Whether an OpenAlex author profile is in AI/ML/CS.

    Prefers the modern ``topics`` (field/subfield) signal and falls back to
    ``x_concepts`` above a score threshold. An author with no topical signal at
    all is treated as non-CS so junk profiles do not slip through.
    """

    for t in record.get("topics") or []:
        field = ((t.get("field") or {}).get("display_name") or "").strip().lower()
        if field in _CS_FIELD_NAMES:
            return True
        sub = ((t.get("subfield") or {}).get("display_name") or "").lower()
        if any(h in sub for h in _AI_SUBFIELD_HINTS):
            return True
    for c in record.get("x_concepts") or []:
        name = (c.get("display_name") or "").strip().lower()
        if name in _CS_CONCEPTS and (c.get("score") or 0) >= concept_threshold:
            return True
    return False


def short_id(openalex_id: Optional[str]) -> Optional[str]:
    """'https://openalex.org/A123' -> 'A123'."""

    if not openalex_id:
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Rebuild plain-text abstract from OpenAlex's abstract_inverted_index."""

    if not inverted_index:
        return ""
    positions: List[tuple] = []
    for word, idxs in inverted_index.items():
        for idx in idxs:
            positions.append((idx, word))
    if not positions:
        return ""
    positions.sort(key=lambda t: t[0])
    return " ".join(word for _, word in positions)


def arxiv_id_from_doi(doi: Optional[str]) -> Optional[str]:
    """Extract a versionless arXiv id from an arXiv DOI.

    '10.48550/arXiv.2401.01234' -> '2401.01234'.
    """

    if not doi:
        return None
    low = doi.lower()
    marker = "arxiv."
    pos = low.find(marker)
    if pos == -1:
        return None
    candidate = doi[pos + len(marker):]
    # strip any version suffix like v2
    if "v" in candidate:
        head, _, tail = candidate.rpartition("v")
        if tail.isdigit():
            candidate = head
    return candidate.strip("/") or None


def _chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _params(mailto: Optional[str], **extra: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = dict(extra)
    if mailto:
        params["mailto"] = mailto
    return params


def _topic_signal(work: Dict[str, Any]) -> "tuple[Optional[str], Optional[str], Optional[str], List[str]]":
    """Extract (primary_topic, field, subfield, all topic fields) from a work.

    OpenAlex classifies every work into a primary_topic plus a short topics list,
    each carrying a domain/field/subfield. The field/subfield of the primary
    topic is the GenAI-scope signal; the union of all topic fields lets the
    classifier see a secondary CS signal on a borderline cross-domain work.
    """

    primary = work.get("primary_topic") or {}
    primary_topic = primary.get("display_name")
    primary_field = ((primary.get("field") or {}).get("display_name"))
    primary_subfield = ((primary.get("subfield") or {}).get("display_name"))

    fields: List[str] = []
    for topic in [primary] + list(work.get("topics") or []):
        if not topic:
            continue
        name = (topic.get("field") or {}).get("display_name")
        if name and name not in fields:
            fields.append(name)
    return primary_topic, primary_field, primary_subfield, fields


def normalize_work(work: Dict[str, Any]) -> Paper:
    """Normalize a raw OpenAlex work record to a Paper."""

    doi = work.get("doi")
    arxiv_id = arxiv_id_from_doi(doi)

    authors: List[PaperAuthor] = []
    for authorship in work.get("authorships", []) or []:
        author = authorship.get("author") or {}
        inst_ids = [
            short_id(inst.get("id"))
            for inst in (authorship.get("institutions") or [])
            if inst.get("id")
        ]
        raw_affils: List[str] = []
        # newer OpenAlex: authorship.raw_affiliation_strings (list)
        for s in authorship.get("raw_affiliation_strings", []) or []:
            if s:
                raw_affils.append(s)
        # also authorship.affiliations[].raw_affiliation_string
        for aff in authorship.get("affiliations", []) or []:
            s = aff.get("raw_affiliation_string")
            if s:
                raw_affils.append(s)
        authors.append(PaperAuthor(
            name=author.get("display_name") or "",
            openalex_id=short_id(author.get("id")),
            institution_ids=[i for i in inst_ids if i],
            raw_affiliation_strings=raw_affils,
        ))

    primary_location = work.get("primary_location") or {}
    landing = primary_location.get("landing_page_url")

    primary_topic, primary_field, primary_subfield, topic_fields = _topic_signal(work)

    return Paper(
        title=work.get("title") or work.get("display_name") or "",
        arxiv_id=arxiv_id,
        doi=doi,
        authors=authors,
        date=work.get("publication_date"),
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        cited_by_count=work.get("cited_by_count") or 0,
        doi_url=doi,
        source_url=landing or short_id(work.get("id")),
        primary_topic=primary_topic,
        primary_field=primary_field,
        primary_subfield=primary_subfield,
        topic_fields=topic_fields,
    )


def _paged_works(
    client: HttpClient,
    filt: str,
    mailto: Optional[str] = None,
    per_page: int = PER_PAGE,
    max_pages: int = 50,
) -> List[Dict[str, Any]]:
    """Cursor-paginate the OpenAlex /works endpoint for one filter string.

    Shared by every works query (by institution, by author). Degrades to the
    pages fetched so far on any transient OpenAlex error rather than aborting.
    """

    out: List[Dict[str, Any]] = []
    cursor = "*"
    pages = 0
    while cursor and pages < max_pages:
        params = _params(
            mailto, filter=filt, per_page=per_page, cursor=cursor,
            select=WORKS_SELECT,
        )
        try:
            data = client.get_json(WORKS_URL, params=params)
        except _OPENALEX_ERRORS:
            # Degrade: keep whatever pages we already fetched rather than abort.
            break
        out.extend(data.get("results", []) or [])
        cursor = (data.get("meta") or {}).get("next_cursor")
        pages += 1
        if not (data.get("results")):
            break
    return out


def works_by_institutions(
    client: HttpClient,
    institution_ids: List[str],
    from_date: str,
    to_date: str,
    mailto: Optional[str] = None,
    per_page: int = PER_PAGE,
    max_pages: int = 50,
) -> List[Dict[str, Any]]:
    """Return raw OpenAlex works authored at any of the given institutions."""

    if not institution_ids:
        return []
    inst_filter = "|".join(short_id(i) for i in institution_ids)
    filt = (
        "authorships.institutions.id:{inst},"
        "from_publication_date:{frm},to_publication_date:{to},"
        "type:article|preprint"
    ).format(inst=inst_filter, frm=from_date, to=to_date)
    return _paged_works(client, filt, mailto, per_page, max_pages)


def works_by_author(
    client: HttpClient,
    author_id: str,
    from_date: str,
    to_date: str,
    mailto: Optional[str] = None,
    per_page: int = PER_PAGE,
    max_pages: int = 10,
) -> List[Dict[str, Any]]:
    """Return raw OpenAlex works for one author id within the date window."""

    aid = short_id(author_id)
    if not aid:
        return []
    filt = (
        "authorships.author.id:{aid},"
        "from_publication_date:{frm},to_publication_date:{to},"
        "type:article|preprint"
    ).format(aid=aid, frm=from_date, to=to_date)
    return _paged_works(client, filt, mailto, per_page, max_pages)


def works_by_dois(
    client: HttpClient,
    dois: List[str],
    mailto: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Batch-fetch works by DOI to enrich arXiv candidates."""

    out: List[Dict[str, Any]] = []
    for chunk in _chunks([d for d in dois if d], OR_CHUNK):
        doi_filter = "|".join(chunk)
        params = _params(
            mailto, filter="doi:" + doi_filter, per_page=PER_PAGE,
            select=WORKS_SELECT,
        )
        try:
            data = client.get_json(WORKS_URL, params=params)
        except _OPENALEX_ERRORS:
            # Skip this batch: its papers simply fall back to the HTML path.
            continue
        out.extend(data.get("results", []) or [])
    return out


def authors_by_ids(
    client: HttpClient,
    author_ids: List[str],
    mailto: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Batch-fetch author profiles by OpenAlex id."""

    ids = [short_id(a) for a in author_ids if a]
    out: List[Dict[str, Any]] = []
    for chunk in _chunks(ids, OR_CHUNK):
        params = _params(
            mailto, filter="openalex:" + "|".join(chunk), per_page=PER_PAGE
        )
        try:
            data = client.get_json(AUTHORS_URL, params=params)
        except _OPENALEX_ERRORS:
            # Skip this batch: those authors just stay un-enriched.
            continue
        out.extend(data.get("results", []) or [])
    return out


def authors_search(
    client: HttpClient,
    name: str,
    mailto: Optional[str] = None,
    per_page: int = 10,
    country_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search OpenAlex authors by display name (best-effort, degrades to []).

    ``country_code`` (e.g. "nl") additionally constrains candidates to authors
    whose last-known institution is in that country -- used to surface the
    NL-based researcher buried under higher-cited namesakes.
    """

    if not name or not name.strip():
        return []
    filt = "display_name.search:" + name.strip()
    if country_code:
        filt += ",last_known_institutions.country_code:" + country_code.strip().lower()
    params = _params(
        mailto,
        filter=filt,
        sort="cited_by_count:desc",
        per_page=per_page,
    )
    try:
        data = client.get_json(AUTHORS_URL, params=params)
    except _OPENALEX_ERRORS:
        return []
    return data.get("results", []) or []


def institutions_search(
    client: HttpClient,
    term: str,
    mailto: Optional[str] = None,
    per_page: int = 5,
    country_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search OpenAlex institutions by name (best-effort, degrades to []).

    Sorted by works_count so the dominant institution for a term (e.g. the real
    "University of Amsterdam") is the first candidate. Used to resolve the
    watchlist institution labels to ids at runtime. ``country_code`` (e.g. "nl")
    constrains candidates to one country so a watchlist NL node never resolves to
    a global/foreign org of the same name (e.g. Qualcomm US, Microsoft UK).
    """

    if not term or not term.strip():
        return []
    filt = "display_name.search:" + term.strip()
    if country_code:
        filt += ",country_code:" + country_code.strip().lower()
    params = _params(
        mailto,
        filter=filt,
        sort="works_count:desc",
        per_page=per_page,
    )
    try:
        data = client.get_json(INSTITUTIONS_URL, params=params)
    except _OPENALEX_ERRORS:
        return []
    return data.get("results", []) or []


def top_authors_by_institution(
    client: HttpClient,
    institution_ids: List[str],
    mailto: Optional[str] = None,
    n: int = 25,
    per_page: int = 50,
) -> List[Dict[str, Any]]:
    """Most-cited authors whose last-known institution is one of these labs."""

    if not institution_ids:
        return []
    inst_filter = "|".join(short_id(i) for i in institution_ids)
    filt = "last_known_institutions.id:" + inst_filter

    out: List[Dict[str, Any]] = []
    page = 1
    while len(out) < n:
        params = _params(
            mailto,
            filter=filt,
            sort="cited_by_count:desc",
            per_page=min(per_page, n - len(out) + per_page),
            page=page,
        )
        try:
            data = client.get_json(AUTHORS_URL, params=params)
        except _OPENALEX_ERRORS:
            # Degrade: rank from whatever pages we already have.
            break
        results = data.get("results", []) or []
        if not results:
            break
        out.extend(results)
        page += 1
        if page > 20:  # hard safety stop
            break
    return out[:n]
