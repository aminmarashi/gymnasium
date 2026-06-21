"""Offline tests for the two-feed query layer: filter, search, sort, facets.

Seeds paper AND repo rows directly into an in-memory DB (no network, no
trackers) and exercises ``university.feed`` plus the facets endpoint. Document
README serving for repos is covered in ``test_university.py``.
"""

import json
import sqlite3

import pytest

from university import db, feed


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    db.bootstrap(c)
    return c


def _insert(conn, kind, ext, title, abstract, signal, published_at, url, raw):
    conn.execute(
        "INSERT INTO corpus_item (kind, external_id, title, source, url, abstract, "
        "why, signal, published_at, ingested_at, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (kind, ext, title, "src", url, abstract, "why", signal, published_at,
         db.utcnow(), json.dumps(raw)))
    conn.commit()


@pytest.fixture
def seeded(conn):
    # Papers
    _insert(conn, "paper", "p1", "Routing in MoE", "a study of routing", 90,
            "2026-06-10", "https://arxiv.org/abs/2601.1",
            {"arxiv_id": "2601.1", "labs_matched": ["google"],
             "authors": [{"name": "Ada Lovelace"}, {"name": "Alan Turing"}]})
    _insert(conn, "paper", "p2", "Scaling Laws", "loss curves", 40,
            "2026-06-20", "https://dl.acm.org/doi/10.1145/xyz",
            {"doi": "10.1145/xyz", "labs_matched": ["openai"],
             "primary_field": "Machine Learning",
             "authors": [{"name": "Alan Turing"}]})
    _insert(conn, "paper", "p3", "Diffusion Models", "image generation", 70,
            "2026-06-01", "https://link.springer.com/article/abc",
            {"labs_matched": ["google", "deepmind"], "primary_field": "Vision",
             "authors": [{"name": "Grace Hopper"}]})
    # Repos
    _insert(conn, "repo", "google/jax", "google/jax", "autodiff library", 80,
            "2025-01-01", "https://github.com/google/jax",
            {"full_name": "google/jax", "owner": "google", "language": "Python",
             "stargazers_count": 20000, "pushed_at": "2026-06-15",
             "created_at": "2025-01-01"})
    _insert(conn, "repo", "meta/llama", "meta/llama", "an llm", 95,
            "2024-01-01", "https://github.com/meta/llama",
            {"full_name": "meta/llama", "owner": "meta", "language": "C++",
             "stargazers_count": 50000, "pushed_at": "2026-06-05"})
    _insert(conn, "repo", "google/flax", "google/flax", "nn library", 30,
            "2025-02-01", "https://github.com/google/flax",
            {"full_name": "google/flax", "owner": "google", "language": "Python",
             "stargazers_count": 5000, "pushed_at": "2026-06-25"})
    return conn


def _rows(conn, kind):
    return conn.execute("SELECT * FROM corpus_item WHERE kind=?", (kind,)).fetchall()


def _titles(rows):
    return [r["title"] for r in rows]


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------
def test_paper_filter_by_author(seeded):
    rows = _rows(seeded, "paper")
    out = feed.select(rows, filters={"author": "Alan Turing"})
    assert set(_titles(out)) == {"Routing in MoE", "Scaling Laws"}


def test_paper_filter_by_company(seeded):
    rows = _rows(seeded, "paper")
    out = feed.select(rows, filters={"company": "google"})
    assert set(_titles(out)) == {"Routing in MoE", "Diffusion Models"}


def test_paper_filter_by_publication(seeded):
    rows = _rows(seeded, "paper")
    assert _titles(feed.select(rows, filters={"publication": "arXiv"})) == ["Routing in MoE"]
    assert _titles(feed.select(rows, filters={"publication": "ACM"})) == ["Scaling Laws"]
    assert _titles(feed.select(rows, filters={"publication": "Springer"})) == ["Diffusion Models"]


def test_repo_filter_by_company_and_language(seeded):
    rows = _rows(seeded, "repo")
    assert set(_titles(feed.select(rows, filters={"company": "google"}))) == {"google/jax", "google/flax"}
    assert _titles(feed.select(rows, filters={"language": "C++"})) == ["meta/llama"]


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------
def test_paper_search_title_abstract_author(seeded):
    rows = _rows(seeded, "paper")
    assert _titles(feed.select(rows, q="routing")) == ["Routing in MoE"]        # title + abstract
    assert set(_titles(feed.select(rows, q="turing"))) == {"Routing in MoE", "Scaling Laws"}  # author


def test_repo_search_description_and_owner(seeded):
    rows = _rows(seeded, "repo")
    assert _titles(feed.select(rows, q="llm")) == ["meta/llama"]                 # description
    assert set(_titles(feed.select(rows, q="google"))) == {"google/jax", "google/flax"}  # owner


# --------------------------------------------------------------------------
# sort
# --------------------------------------------------------------------------
def test_paper_sort_recency_vs_rating(seeded):
    rows = _rows(seeded, "paper")
    assert _titles(feed.select(rows, sort="recency")) == ["Scaling Laws", "Routing in MoE", "Diffusion Models"]
    assert _titles(feed.select(rows, sort="rating")) == ["Routing in MoE", "Diffusion Models", "Scaling Laws"]


def test_repo_sort_recency_vs_rating(seeded):
    rows = _rows(seeded, "repo")
    # recency = pushed_at desc
    assert _titles(feed.select(rows, sort="recency")) == ["google/flax", "google/jax", "meta/llama"]
    # rating = signal desc
    assert _titles(feed.select(rows, sort="rating")) == ["meta/llama", "google/jax", "google/flax"]


# --------------------------------------------------------------------------
# facets
# --------------------------------------------------------------------------
def _as_counts(facet):
    return {v["value"]: v["count"] for v in facet["values"]}


def test_paper_facets(seeded):
    f = feed.facets(_rows(seeded, "paper"), "paper")
    assert _as_counts(f["companies"]) == {"google": 2, "openai": 1, "deepmind": 1}
    assert _as_counts(f["publications"]) == {"arXiv": 1, "ACM": 1, "Springer": 1}
    assert _as_counts(f["authors"]) == {"Alan Turing": 2, "Ada Lovelace": 1, "Grace Hopper": 1}
    assert f["companies"]["capped"] is False


def test_repo_facets(seeded):
    f = feed.facets(_rows(seeded, "repo"), "repo")
    assert _as_counts(f["companies"]) == {"google": 2, "meta": 1}
    assert _as_counts(f["languages"]) == {"Python": 2, "C++": 1}


def test_facets_cap_flags_truncation(seeded):
    f = feed.facets(_rows(seeded, "paper"), "paper", cap=1)
    assert len(f["companies"]["values"]) == 1
    assert f["companies"]["capped"] is True
    assert f["companies"]["total"] == 3
