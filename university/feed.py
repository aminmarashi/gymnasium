"""Feed query helpers: parse raw_json, derive filter facets, search & sort.

There are only a few hundred corpus items, so the feed query selects the rows
for a ``kind`` and then filters / searches / sorts them in Python over the
parsed ``raw_json`` — no schema change or migration is needed. Every function
here is pure (operates on sqlite3.Row objects and plain dicts) so the server
endpoints and the tests can share the exact same derivation logic.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Dict, List, Optional

# Publisher derivation: a substring found in the paper's source/DOI/abs url maps
# to a human venue label. Order matters — first match wins.
_PUBLISHER_HOSTS = [
    ("dl.acm.org", "ACM"),
    ("mdpi", "MDPI"),
    ("link.springer", "Springer"),
    ("springer", "Springer"),
    ("ieee", "IEEE"),
    ("sciencedirect", "Elsevier"),
    ("elsevier", "Elsevier"),
    ("nature.com", "Nature"),
    ("openreview", "OpenReview"),
    ("aclanthology", "ACL"),
    ("neurips.cc", "NeurIPS"),
    ("nips.cc", "NeurIPS"),
    ("pnas.org", "PNAS"),
    ("biorxiv", "bioRxiv"),
    ("wiley", "Wiley"),
    ("plos", "PLOS"),
]


def parse_raw(row) -> dict:
    """Parse a row's ``raw_json`` to a dict, tolerating null / malformed JSON."""
    try:
        raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
    except (ValueError, TypeError):
        raw = {}
    return raw if isinstance(raw, dict) else {}


def paper_authors(raw: dict) -> List[str]:
    """The author display names for a paper (``authors[].name`` or bare names)."""
    out = []
    for a in raw.get("authors") or []:
        name = a.get("name") if isinstance(a, dict) else a
        if name:
            out.append(str(name))
    return out


def paper_companies(raw: dict) -> List[str]:
    """The labs/orgs a paper was matched to (``labs_matched``)."""
    return [str(c) for c in (raw.get("labs_matched") or []) if c]


def repo_company(raw: dict) -> str:
    """The owner / giant org for a repo (``owner``, else the full_name prefix)."""
    owner = raw.get("owner")
    if owner:
        return str(owner)
    full = raw.get("full_name") or ""
    return full.split("/", 1)[0] if "/" in full else ""


def repo_language(raw: dict) -> str:
    return str(raw.get("language") or "")


def derive_publication(url: Optional[str], raw: dict) -> str:
    """Derive a venue: "arXiv" for arXiv papers, else a publisher, else field."""
    blob = " ".join(
        str(x) for x in (
            raw.get("abs_url"), raw.get("source_url"), url, raw.get("doi"),
            raw.get("doi_url"), raw.get("pdf_url"),
        ) if x
    ).lower()
    if (raw.get("arxiv_id") or "").strip() or "arxiv.org" in blob or "10.48550/arxiv" in blob:
        return "arXiv"
    for needle, label in _PUBLISHER_HOSTS:
        if needle in blob:
            return label
    return raw.get("primary_field") or "Other"


def item_facets(row, raw: dict) -> dict:
    """The derived filter/card fields surfaced in the item JSON for one row."""
    if row["kind"] == "repo":
        return {
            "authors": [],
            "company": repo_company(raw),
            "publication": None,
            "language": repo_language(raw),
            "stars": raw.get("stargazers_count"),
        }
    companies = paper_companies(raw)
    return {
        "authors": paper_authors(raw),
        "company": ", ".join(companies),
        "publication": derive_publication(row["url"], raw),
        "language": None,
        "stars": None,
    }


def _matches_query(row, raw: dict, q: str) -> bool:
    """Case-insensitive substring match over title, abstract, source, people."""
    hay = [row["title"], row["abstract"], row["source"]]
    if row["kind"] == "repo":
        hay.append(repo_company(raw))
    else:
        hay.extend(paper_authors(raw))
    q = q.lower()
    return any(q in (h or "").lower() for h in hay if h)


def _passes_filters(row, raw: dict, filters: Dict[str, Optional[str]]) -> bool:
    if row["kind"] == "repo":
        if filters.get("company") and filters["company"] != repo_company(raw):
            return False
        if filters.get("language") and filters["language"] != repo_language(raw):
            return False
        return True
    if filters.get("author") and filters["author"] not in paper_authors(raw):
        return False
    if filters.get("company") and filters["company"] not in paper_companies(raw):
        return False
    if filters.get("publication") and filters["publication"] != derive_publication(row["url"], raw):
        return False
    return True


def _recency_key(row, raw: dict) -> str:
    """Recency timestamp: published_at for papers, pushed_at|created_at for repos.

    ISO-8601 strings sort lexicographically, so a plain string compare orders
    newest-first under ``reverse=True``. Missing dates sort last.
    """
    if row["kind"] == "repo":
        return raw.get("pushed_at") or raw.get("created_at") or row["published_at"] or ""
    return row["published_at"] or ""


def select(rows, q: str = "", sort: str = "recency",
           filters: Optional[Dict[str, Optional[str]]] = None,
           limit: Optional[int] = None) -> list:
    """Filter + search + sort the given rows, returning a new ordered list.

    ``sort`` is "recency" (newest first) or "rating" (signal, descending). Both
    break ties on signal then id so the order is stable and deterministic.
    """
    filters = filters or {}
    out = []
    for row in rows:
        raw = parse_raw(row)
        if q and not _matches_query(row, raw, q):
            continue
        if not _passes_filters(row, raw, filters):
            continue
        out.append((row, raw))

    if sort == "rating":
        out.sort(key=lambda rr: ((rr[0]["signal"] or 0), _recency_key(*rr), rr[0]["id"]),
                 reverse=True)
    else:  # recency (default)
        out.sort(key=lambda rr: (_recency_key(*rr), (rr[0]["signal"] or 0), rr[0]["id"]),
                 reverse=True)

    result = [row for row, _ in out]
    if limit is not None:
        result = result[:limit]
    return result


def _top(counter: Counter, cap: int) -> dict:
    """Top-``cap`` values by count (then name), flagging whether it was capped."""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return {
        "values": [{"value": v, "count": n} for v, n in items[:cap]],
        "capped": len(items) > cap,
        "total": len(items),
    }


def facets(rows, kind: str, cap: int = 50) -> dict:
    """Distinct filter values WITH counts for a kind's dropdowns (top ``cap``)."""
    if kind == "repo":
        companies, languages = Counter(), Counter()
        for row in rows:
            raw = parse_raw(row)
            c = repo_company(raw)
            if c:
                companies[c] += 1
            lang = repo_language(raw)
            if lang:
                languages[lang] += 1
        return {"companies": _top(companies, cap), "languages": _top(languages, cap)}

    authors, companies, publications = Counter(), Counter(), Counter()
    for row in rows:
        raw = parse_raw(row)
        for a in paper_authors(raw):
            authors[a] += 1
        for c in paper_companies(raw):
            companies[c] += 1
        publications[derive_publication(row["url"], raw)] += 1
    return {
        "authors": _top(authors, cap),
        "companies": _top(companies, cap),
        "publications": _top(publications, cap),
    }
