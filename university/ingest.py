"""Ingest the labpapers / labrepos JSON report sidecars into corpus_item.

The trackers already write ``reports/<tracker>_<date>_<window>.json`` sidecars
(see labpapers.report / labrepos.report). We read those, map each paper/repo to
a ``corpus_item`` row, normalize a 0..100 ``signal``, and upsert deduped by
``(kind, external_id)``. Documents are NOT downloaded here — that is lazy and
lives in docs.ensure_document.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

from .db import utcnow


# --------------------------------------------------------------------------
# Field mapping
# --------------------------------------------------------------------------
def _paper_external_id(p: dict) -> str:
    return (
        p.get("arxiv_id")
        or p.get("doi")
        or p.get("source_url")
        or p.get("abs_url")
        or p.get("title", "")
    )


def _paper_url(p: dict) -> Optional[str]:
    return (
        p.get("abs_url")
        or p.get("pdf_url")
        or p.get("source_url")
        or p.get("doi_url")
        or p.get("doi")
    )


def _normalize_signal(raw: float, lo: float, hi: float) -> int:
    """Map a raw value into 0..100 by log-scaled min/max over the batch."""
    if hi <= lo:
        return 50
    # log scale so a handful of mega-cited items don't flatten everyone else.
    def lg(v: float) -> float:
        return math.log10(max(0.0, v) + 1.0)

    frac = (lg(raw) - lg(lo)) / (lg(hi) - lg(lo)) if lg(hi) > lg(lo) else 0.5
    return max(0, min(100, int(round(frac * 100))))


def _map_paper(p: dict, lo: float, hi: float) -> dict:
    ext = _paper_external_id(p)
    raw = float(p.get("max_author_cited_by") or p.get("sum_author_cited_by") or 0)
    fields = []
    if p.get("primary_field"):
        fields.append(p["primary_field"])
    for lab in (p.get("labs_matched") or [])[:2]:
        fields.append(lab)
    why = p.get("impact_summary") or (p.get("abstract") or "")[:200]
    return {
        "kind": "paper",
        "external_id": str(ext),
        "title": p.get("title") or "(untitled paper)",
        "source": ", ".join(p.get("labs_matched") or []) or p.get("primary_field") or "arXiv",
        "url": _paper_url(p),
        "abstract": p.get("abstract"),
        "why": why,
        "signal": _normalize_signal(raw, lo, hi),
        "published_at": p.get("date"),
        "tags": fields,
    }


def _map_repo(r: dict, lo: float, hi: float) -> dict:
    ext = r.get("full_name") or "{}/{}".format(r.get("owner", ""), r.get("name", ""))
    raw = float(r.get("stargazers_count") or 0)
    tags = []
    if r.get("language"):
        tags.append(r["language"])
    for t in (r.get("topics") or [])[:2]:
        tags.append(t)
    why = r.get("description") or "Repository from a tracked lab."
    return {
        "kind": "repo",
        "external_id": str(ext),
        "title": r.get("full_name") or ext,
        "source": "GitHub · {} stars".format(r.get("stargazers_count", 0)),
        "url": r.get("html_url"),
        "abstract": r.get("description"),
        "why": why,
        "signal": _normalize_signal(raw, lo, hi),
        "published_at": r.get("created_at") or r.get("pushed_at"),
        "tags": tags,
    }


def _upsert(conn: sqlite3.Connection, row: dict, raw: dict) -> bool:
    """Insert or update one corpus_item. Returns True if a new row was created."""
    now = utcnow()
    existing = conn.execute(
        "SELECT id FROM corpus_item WHERE kind=? AND external_id=?",
        (row["kind"], row["external_id"]),
    ).fetchone()
    payload = (
        row["title"], row["source"], row["url"], row["abstract"], row["why"],
        row["signal"], row["published_at"], json.dumps(raw, ensure_ascii=False),
    )
    if existing is None:
        conn.execute(
            "INSERT INTO corpus_item (kind, external_id, title, source, url, "
            "abstract, why, signal, published_at, ingested_at, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (row["kind"], row["external_id"]) + payload[:-1] + (now, payload[-1]),
        )
        return True
    # Refresh mutable fields but keep ingested_at, summaries, and doc state.
    conn.execute(
        "UPDATE corpus_item SET title=?, source=?, url=?, abstract=?, why=?, "
        "signal=?, published_at=?, raw_json=? WHERE id=?",
        payload + (existing["id"],),
    )
    return False


def _read_sidecar(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _ingest_payload(conn: sqlite3.Connection, data: dict) -> Tuple[int, int]:
    """Ingest one parsed sidecar dict. Returns (new, updated) counts."""
    new = updated = 0
    papers = data.get("papers") or []
    repos = data.get("repos") or []
    if papers:
        vals = [float(p.get("max_author_cited_by") or p.get("sum_author_cited_by") or 0) for p in papers]
        lo, hi = (min(vals), max(vals)) if vals else (0.0, 0.0)
        for p in papers:
            row = _map_paper(p, lo, hi)
            if _upsert(conn, row, p):
                new += 1
            else:
                updated += 1
    if repos:
        vals = [float(r.get("stargazers_count") or 0) for r in repos]
        lo, hi = (min(vals), max(vals)) if vals else (0.0, 0.0)
        for r in repos:
            row = _map_repo(r, lo, hi)
            if _upsert(conn, row, r):
                new += 1
            else:
                updated += 1
    conn.commit()
    return new, updated


_SIDECAR_RE = re.compile(r"^(labpapers|labrepos)_\d{4}-\d{2}-\d{2}_\d+d\.json$")


def _sidecar_files(reports_dir: str) -> List[str]:
    if not os.path.isdir(reports_dir):
        return []
    out = []
    for name in os.listdir(reports_dir):
        if _SIDECAR_RE.match(name):
            out.append(os.path.join(reports_dir, name))
    return sorted(out)


def ingest_reports(reports_dir: str, conn: sqlite3.Connection) -> Dict[str, int]:
    """Ingest EVERY tracker sidecar found under reports_dir. Idempotent."""
    new = updated = files = 0
    for path in _sidecar_files(reports_dir):
        data = _read_sidecar(path)
        n, u = _ingest_payload(conn, data)
        new += n
        updated += u
        files += 1
    return {"files": files, "new": new, "updated": updated}


def ingest_latest(reports_dir: str, conn: sqlite3.Connection) -> Dict[str, int]:
    """Ingest only the newest sidecar per tracker (by filename date+window)."""
    latest: Dict[str, str] = {}
    for path in _sidecar_files(reports_dir):
        tracker = os.path.basename(path).split("_", 1)[0]
        # filenames sort chronologically because of the YYYY-MM-DD stamp.
        if tracker not in latest or os.path.basename(path) > os.path.basename(latest[tracker]):
            latest[tracker] = path
    new = updated = 0
    for path in latest.values():
        n, u = _ingest_payload(conn, _read_sidecar(path))
        new += n
        updated += u
    return {"files": len(latest), "new": new, "updated": updated}
