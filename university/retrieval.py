"""Knowledge-grounded retrieval for the article chat.

``retrieve_context`` builds a small, bounded context bundle for a chat about a
whole article. It draws on the user's OWN saved knowledge — the FTS5 index over
``kb_entry``/``kb_message`` and the concept map (``concept``/``concept_edge``) —
plus a short excerpt of the article itself. No new dependencies, no embeddings:
retrieval is keyword/FTS5 based and the function is pure and unit-testable.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Dict, List, Optional

# Bounds — keep the injected context small so the prompt stays tight.
MAX_NOTES = 6
MAX_CONCEPTS = 10
MAX_EDGES = 12
MAX_DEF_CHARS = 400
MAX_EXCERPT_CHARS = 800
MAX_TOKENS = 12


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z0-9]+", (text or "").lower()) if len(t) >= 3]


def _get(item, key, default=None):
    """Read a key from either a dict or a sqlite3.Row (or return default)."""
    if item is None:
        return default
    try:
        if isinstance(item, dict):
            return item.get(key, default)
        return item[key]
    except (KeyError, IndexError):
        return default


def _article_excerpt(item) -> str:
    """Short readable excerpt of the article: summary if present, else abstract."""
    summary = _get(item, "summary_readable")
    text = ""
    if isinstance(summary, list) and summary:
        text = " ".join(str(s) for s in summary)
    elif isinstance(summary, str) and summary.strip():
        text = summary
    if not text:
        text = _get(item, "abstract") or _get(item, "why") or ""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) > MAX_EXCERPT_CHARS:
        text = text[:MAX_EXCERPT_CHARS].rstrip() + "…"
    return text


def _definition(lead: Optional[str], body: Optional[str]) -> str:
    parts = [p for p in [(lead or "").strip(), (body or "").strip()] if p]
    text = " — ".join(parts)
    if len(text) > MAX_DEF_CHARS:
        text = text[:MAX_DEF_CHARS].rstrip() + "…"
    return text


def _kb_notes(conn: sqlite3.Connection, item_id: Optional[int],
              tokens: List[str]) -> List[dict]:
    """Top FTS-relevant kb notes for the query, plus any tied to this article."""
    notes: List[dict] = []
    seen = set()

    def _add(row):
        eid = int(row["id"])
        if eid in seen:
            return
        seen.add(eid)
        notes.append({
            "id": eid,
            "term": row["term"],
            "definition": _definition(row["lead"], row["body"]),
            "source": row["source_title"] or row["source_url"] or "your notes",
        })

    sel = (
        "SELECT e.id, e.term, e.lead, e.body, e.source_url, "
        "       c.title AS source_title "
        "FROM kb_entry e LEFT JOIN corpus_item c ON c.id = e.item_id "
    )

    # Notes already tied to this exact article come first — they are the most
    # relevant grounding for a chat about it.
    if item_id:
        rows = conn.execute(
            sel + "WHERE e.item_id = ? AND (e.mode IS NULL OR e.mode != 'chat') "
            "ORDER BY e.id DESC", (int(item_id),)
        ).fetchall()
        for r in rows:
            _add(r)
            if len(notes) >= MAX_NOTES:
                return notes

    # Then the best FTS matches for the query terms / article title.
    if tokens:
        match = " OR ".join('"{}"*'.format(t) for t in tokens)
        try:
            rows = conn.execute(
                "SELECT e.id, e.term, e.lead, e.body, e.source_url, "
                "       c.title AS source_title "
                "FROM kb_fts f JOIN kb_entry e ON e.id = f.entry_id "
                "LEFT JOIN corpus_item c ON c.id = e.item_id "
                "WHERE kb_fts MATCH ? AND (e.mode IS NULL OR e.mode != 'chat') "
                "ORDER BY rank", (match,)
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for r in rows:
            _add(r)
            if len(notes) >= MAX_NOTES:
                break
    return notes[:MAX_NOTES]


def _graph(conn: sqlite3.Connection, item_id: Optional[int],
           tokens: List[str]) -> Dict[str, List]:
    """Concepts tied to this article + their 1-hop neighbours + label matches."""
    chosen: "Dict[int, str]" = {}  # concept id -> label

    def _take(rows):
        for r in rows:
            if len(chosen) >= MAX_CONCEPTS:
                break
            chosen.setdefault(int(r["id"]), r["label"])

    # Concepts whose kb_entry is tied to this article.
    if item_id:
        _take(conn.execute(
            "SELECT cn.id, cn.label FROM concept cn "
            "JOIN kb_entry e ON e.id = cn.kb_entry_id "
            "WHERE e.item_id = ? ORDER BY cn.id", (int(item_id),)
        ).fetchall())

    # 1-hop neighbours of the concepts chosen so far, via concept_edge.
    if chosen:
        seeds = list(chosen.keys())
        placeholders = ",".join("?" for _ in seeds)
        neigh = conn.execute(
            "SELECT cn.id, cn.label FROM concept cn JOIN concept_edge ed "
            "ON (ed.dst_concept_id = cn.id AND ed.src_concept_id IN ({p})) "
            "   OR (ed.src_concept_id = cn.id AND ed.dst_concept_id IN ({p})) "
            "ORDER BY cn.id".format(p=placeholders),
            seeds + seeds,
        ).fetchall()
        _take(neigh)

    # Any concept whose label matches the query terms.
    if tokens and len(chosen) < MAX_CONCEPTS:
        clause = " OR ".join("LOWER(label) LIKE ?" for _ in tokens)
        params = ["%{}%".format(t) for t in tokens]
        _take(conn.execute(
            "SELECT id, label FROM concept WHERE " + clause + " ORDER BY id",
            params,
        ).fetchall())

    ids = list(chosen.keys())
    edges: List[str] = []
    if len(ids) >= 2:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            "SELECT src_concept_id AS s, dst_concept_id AS d FROM concept_edge "
            "WHERE src_concept_id IN ({p}) AND dst_concept_id IN ({p}) "
            "ORDER BY id".format(p=placeholders),
            ids + ids,
        ).fetchall()
        for r in rows:
            if len(edges) >= MAX_EDGES:
                break
            a, b = chosen.get(int(r["s"])), chosen.get(int(r["d"]))
            if a and b:
                edges.append("{} -- {}".format(a, b))

    return {
        "concepts": [chosen[i] for i in ids],
        "edges": edges,
    }


def retrieve_context(conn: sqlite3.Connection, item, query: str) -> Dict[str, object]:
    """Build a bounded, knowledge-grounded context bundle for an article chat.

    Returns a dict with:
      ``notes``    -> [{id, term, definition, source}] from the user's KB (FTS)
      ``concepts`` -> [label, ...] from the user's concept map
      ``edges``    -> ["A -- B", ...] relations between those concepts
      ``excerpt``  -> a short readable excerpt of the article itself
      ``grounded`` -> {"notes": [term, ...], "concepts": [label, ...]} a small
                      list of what was injected, for the UI / verification.
    """
    item_id = _get(item, "id")
    title = _get(item, "title") or ""
    # Search on the query terms AND the article title.
    tokens: List[str] = []
    for t in _tokens(query) + _tokens(title):
        if t not in tokens:
            tokens.append(t)
    tokens = tokens[:MAX_TOKENS]

    notes = _kb_notes(conn, item_id, tokens)
    graph = _graph(conn, item_id, tokens)
    excerpt = _article_excerpt(item)

    return {
        "notes": notes,
        "concepts": graph["concepts"],
        "edges": graph["edges"],
        "excerpt": excerpt,
        "grounded": {
            "notes": [n["term"] for n in notes],
            "concepts": list(graph["concepts"]),
        },
    }
