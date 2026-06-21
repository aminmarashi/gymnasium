"""On-disk document store.

When an item is opened (or a fact is saved) we fetch the original document
once and keep it on disk, so a saved fact always points at a concrete file
even if the upstream source later disappears. Downloads use stdlib urllib and
failure is non-fatal: a down source must never block reading or saving.

Layout (relative to docs_dir):
    papers/<arxiv-id-or-slug>/  source.pdf | source.html, abstract.txt, metadata.json
    repos/<owner>__<name>/      README.md, metadata.json
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.request
import urllib.error
from typing import Optional

from .db import utcnow

USER_AGENT = "GymnasiumUniversity/0.1 (+personal-research)"
_TIMEOUT = 30


def _safe_slug(value: str, fallback: str = "item") -> str:
    value = (value or "").strip()
    # arXiv ids and DOIs contain '/', '.', ':' — keep it filesystem-safe.
    value = re.sub(r"^https?://", "", value)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return slug[:120] or fallback


def _fetch(url: str) -> Optional[bytes]:
    """Best-effort GET. Returns bytes or None (never raises)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        print("[docs] fetch failed for {}: {}".format(url, exc))
        return None


def _paper_dir_slug(item: sqlite3.Row, raw: dict) -> str:
    ext = raw.get("arxiv_id") or item["external_id"]
    return _safe_slug(str(ext), "paper")


def _repo_dir_slug(item: sqlite3.Row, raw: dict) -> str:
    owner = raw.get("owner") or ""
    name = raw.get("name") or ""
    if owner and name:
        return "{}__{}".format(_safe_slug(owner, "owner"), _safe_slug(name, "repo"))
    return _safe_slug(item["external_id"], "repo")


def _store_paper(item: sqlite3.Row, raw: dict, docs_dir: str) -> Optional[str]:
    slug = _paper_dir_slug(item, raw)
    rel_dir = os.path.join("papers", slug)
    abs_dir = os.path.join(docs_dir, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    # metadata + abstract are always written from what we already hold.
    with open(os.path.join(abs_dir, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(raw or {}, fh, ensure_ascii=False, indent=2)
    abstract = item["abstract"] or raw.get("abstract") or ""
    with open(os.path.join(abs_dir, "abstract.txt"), "w", encoding="utf-8") as fh:
        fh.write(abstract)

    # original document: prefer the PDF, fall back to the abstract HTML page.
    pdf_url = raw.get("pdf_url")
    html_url = raw.get("abs_url") or item["url"] or raw.get("source_url")
    doc_rel = None
    if pdf_url:
        data = _fetch(pdf_url)
        if data:
            with open(os.path.join(abs_dir, "source.pdf"), "wb") as fh:
                fh.write(data)
            doc_rel = os.path.join(rel_dir, "source.pdf")
    if doc_rel is None and html_url:
        data = _fetch(html_url)
        if data:
            with open(os.path.join(abs_dir, "source.html"), "wb") as fh:
                fh.write(data)
            doc_rel = os.path.join(rel_dir, "source.html")
    if doc_rel is None:
        # Even with no network, keep the abstract as the canonical local doc.
        doc_rel = os.path.join(rel_dir, "abstract.txt")
    return doc_rel


def _store_repo(item: sqlite3.Row, raw: dict, docs_dir: str) -> Optional[str]:
    slug = _repo_dir_slug(item, raw)
    rel_dir = os.path.join("repos", slug)
    abs_dir = os.path.join(docs_dir, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    with open(os.path.join(abs_dir, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(raw or {}, fh, ensure_ascii=False, indent=2)

    owner = raw.get("owner") or ""
    name = raw.get("name") or ""
    readme_text = None
    if owner and name:
        for branch in ("main", "master"):
            url = "https://raw.githubusercontent.com/{}/{}/{}/README.md".format(owner, name, branch)
            data = _fetch(url)
            if data:
                readme_text = data
                break
    readme_path = os.path.join(abs_dir, "README.md")
    if readme_text is not None:
        with open(readme_path, "wb") as fh:
            fh.write(readme_text)
    else:
        # Fall back to the description so there's always a readable file.
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write((item["abstract"] or raw.get("description") or item["title"] or ""))
    return os.path.join(rel_dir, "README.md")


def _item_dir_rel(item: sqlite3.Row) -> str:
    """Repo-relative document folder for an item (papers/<slug> | repos/<slug>).

    Reuses the same slug logic as the document store so an attached markdown
    file lands next to the item's other artifacts.
    """
    try:
        raw = json.loads(item["raw_json"]) if item["raw_json"] else {}
    except (ValueError, TypeError):
        raw = {}
    if item["kind"] == "repo":
        return os.path.join("repos", _repo_dir_slug(item, raw))
    return os.path.join("papers", _paper_dir_slug(item, raw))


def save_markdown(item: sqlite3.Row, content: str, docs_dir: str) -> str:
    """Write uploaded markdown as ``article.md`` in the item's doc folder.

    Returns the repo-relative path. Overwrites any prior attachment (idempotent).
    """
    rel_dir = _item_dir_rel(item)
    abs_dir = os.path.join(docs_dir, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    with open(os.path.join(abs_dir, "article.md"), "w", encoding="utf-8") as fh:
        fh.write(content)
    return os.path.join(rel_dir, "article.md")


def read_markdown(item: sqlite3.Row, docs_dir: str) -> Optional[str]:
    """Return the stored markdown text for an item, or None when absent."""
    rel = item["markdown_path"]
    if not rel:
        return None
    abs_path = os.path.join(docs_dir, rel)
    if not os.path.isfile(abs_path):
        return None
    with open(abs_path, "r", encoding="utf-8") as fh:
        return fh.read()


def auto_markdown(item: sqlite3.Row, docs_dir: str, conn: sqlite3.Connection) -> Optional[str]:
    """Convert the item's stored original (PDF/HTML) to Markdown and cache it.

    Ensures the original document is on disk (reusing ``ensure_document``), then
    runs microsoft/markitdown over the stored ``source.pdf``/``source.html`` and
    writes the result as ``article.auto.md`` next to the item's other artifacts.
    Returns the converted text, or ``None`` when conversion is not possible
    (markitdown missing, no source document, or any conversion error) so the
    reader degrades gracefully to the abstract view.
    """
    doc_rel = ensure_document(item, docs_dir, conn)
    if not doc_rel:
        return None
    # Only real source documents convert; the abstract.txt fallback is not one.
    base = os.path.basename(doc_rel)
    if base not in ("source.pdf", "source.html"):
        return None
    abs_src = os.path.join(docs_dir, doc_rel)
    if not os.path.isfile(abs_src):
        return None
    try:
        from markitdown import MarkItDown  # third-party; guarded import.

        text = MarkItDown().convert(abs_src).text_content
    except Exception as exc:  # ImportError or any conversion failure.
        print("[docs] auto markdown failed for item {}: {}".format(item["id"], exc))
        return None
    if text is None:
        return None
    rel_dir = os.path.dirname(doc_rel)
    abs_dir = os.path.join(docs_dir, rel_dir)
    try:
        os.makedirs(abs_dir, exist_ok=True)
        with open(os.path.join(abs_dir, "article.auto.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        print("[docs] auto markdown write failed for item {}: {}".format(item["id"], exc))
        return None
    return text


def read_auto_markdown(item: sqlite3.Row, docs_dir: str) -> Optional[str]:
    """Return the cached ``article.auto.md`` text for an item, or None when absent."""
    rel_dir = _item_dir_rel(item)
    abs_path = os.path.join(docs_dir, rel_dir, "article.auto.md")
    if not os.path.isfile(abs_path):
        return None
    with open(abs_path, "r", encoding="utf-8") as fh:
        return fh.read()


def has_convertible_source(item: sqlite3.Row, docs_dir: str) -> bool:
    """Cheap check: is a real source doc already on disk that could convert?

    Does NOT fetch or convert — only inspects the stored ``doc_path``. Used by
    the item endpoint to advertise a ``markdown_available`` flag without work.
    """
    doc_rel = item["doc_path"]
    if not doc_rel:
        return False
    if os.path.basename(doc_rel) not in ("source.pdf", "source.html"):
        return False
    return os.path.isfile(os.path.join(docs_dir, doc_rel))


def ensure_document(item: sqlite3.Row, docs_dir: str, conn: sqlite3.Connection) -> Optional[str]:
    """Ensure the original document is on disk; set doc_path. Idempotent.

    Returns the relative doc_path, or None if nothing could be stored.
    """
    # Idempotent: if we already have a path AND the file exists, skip.
    existing = item["doc_path"]
    if existing and os.path.isfile(os.path.join(docs_dir, existing)):
        return existing

    try:
        raw = json.loads(item["raw_json"]) if item["raw_json"] else {}
    except (ValueError, TypeError):
        raw = {}

    try:
        if item["kind"] == "repo":
            doc_rel = _store_repo(item, raw, docs_dir)
        else:
            doc_rel = _store_paper(item, raw, docs_dir)
    except OSError as exc:
        print("[docs] store failed for item {}: {}".format(item["id"], exc))
        return None

    if doc_rel:
        conn.execute(
            "UPDATE corpus_item SET doc_path=?, doc_fetched_at=? WHERE id=?",
            (doc_rel, utcnow(), item["id"]),
        )
        conn.commit()
    return doc_rel
