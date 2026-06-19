from labpapers.cache import Cache
from labpapers.model import Author, Paper, PaperAuthor
from labpapers.sources import authors


def _prof(aid, name, cited, h=10, is_cs=True):
    return Author(openalex_id=aid, name=name, cited_by_count=cited, h_index=h,
                  is_giant=cited >= 10000, is_cs=is_cs)


def test_rank_authors_from_papers_orders_by_citations():
    prominence = {
        "A1": _prof("A1", "Big Name", 30000),
        "A2": _prof("A2", "Mid", 500),
        "A3": _prof("A3", "Other Lab", 999999),
    }
    p1 = Paper(
        title="p1", labs_matched=["deepseek"],
        authors=[PaperAuthor(name="Big Name", openalex_id="A1"),
                 PaperAuthor(name="Mid", openalex_id="A2")],
    )
    # A3 is on a non-deepseek paper, must not appear in deepseek ranking
    p2 = Paper(
        title="p2", labs_matched=["openai"],
        authors=[PaperAuthor(name="Other Lab", openalex_id="A3")],
    )
    ranked = authors.rank_authors_from_papers("deepseek", [p1, p2], prominence)
    assert [a.openalex_id for a in ranked] == ["A1", "A2"]
    assert ranked[0].lab == "deepseek"
    assert ranked[0].is_giant is True


def test_merge_overall_dedupes_and_sorts():
    per_lab = {
        "deepseek": [_prof("A1", "Big", 30000)],
        "openai": [_prof("A1", "Big", 30000), _prof("A2", "Mid", 500)],
        "meta": [_prof("A4", "Huge", 90000)],
    }
    overall = authors.merge_overall(per_lab, n=10)
    ids = [a.openalex_id for a in overall]
    assert ids == ["A4", "A1", "A2"]  # sorted desc, A1 deduped


def test_enrich_paper_authors_sets_prominence_known():
    prominence = {"A1": _prof("A1", "Big", 30000)}
    refs = [PaperAuthor(name="Big", openalex_id="A1"),
            PaperAuthor(name="NoId")]
    authors.enrich_paper_authors(refs, prominence)
    assert refs[0].prominence_known is True
    assert refs[0].cited_by_count == 30000
    assert refs[0].is_giant is True
    assert refs[1].prominence_known is False


def test_rank_authors_from_papers_drops_non_cs_and_personas():
    prominence = {
        "A1": _prof("A1", "Real CS Person", 30000, is_cs=True),
        "A2": _prof("A2", "Urologist", 99999, is_cs=False),  # high cites, not CS
        "A3": _prof("A3", "Ace (Claude Opus, Anthropic)", 0, is_cs=True),
    }
    p = Paper(
        title="p", labs_matched=["anthropic"],
        authors=[
            PaperAuthor(name="Real CS Person", openalex_id="A1"),
            PaperAuthor(name="Urologist", openalex_id="A2"),
            PaperAuthor(name="Ace (Claude Opus, Anthropic)", openalex_id="A3",
                        raw_affiliation_strings=["Anthropic"]),
        ],
    )
    ranked = authors.rank_authors_from_papers("anthropic", [p], prominence)
    assert [a.openalex_id for a in ranked] == ["A1"]


def test_merge_overall_is_pure_prominence_sort():
    # People are field-filtered to AI/CS upstream, so Overall is a straight
    # global prominence sort: a high-cite person outranks a low-cite one
    # regardless of lab (no per-lab interleave).
    per_lab = {
        "google": [_prof("G1", "G1", 200000), _prof("G2", "G2", 150000),
                   _prof("G3", "G3", 120000)],
        "openai": [_prof("O1", "O1", 90000)],
        "meta": [_prof("M1", "M1", 80000)],
    }
    overall = authors.merge_overall(per_lab, n=10)
    ids = [a.openalex_id for a in overall]
    assert ids == ["G1", "G2", "G3", "O1", "M1"]


def test_best_name_match_picks_cs_and_skips_ambiguous():
    def rec(aid, name, cited, cs=True):
        topics = [{"field": {"display_name": "Computer Science"}}] if cs else \
            [{"field": {"display_name": "Medicine"}}]
        return {"id": "https://openalex.org/" + aid, "display_name": name,
                "cited_by_count": cited, "topics": topics}

    # exactly one AI/CS exact-name match -> picked (the non-CS namesake dropped)
    records = [rec("A1", "Jane Doe", 5000, cs=True),
               rec("A2", "Jane Doe", 9000, cs=False),
               rec("A3", "John Smith", 1, cs=True)]
    m = authors._best_name_match("Jane Doe", records)
    assert m and m["id"].endswith("A1")

    # two AI/CS authors share the name -> ambiguous -> skip
    ambiguous = [rec("B1", "Wei Wang", 4000, cs=True),
                 rec("B2", "Wei Wang", 3000, cs=True)]
    assert authors._best_name_match("Wei Wang", ambiguous) is None

    # no exact-name match at all -> skip
    assert authors._best_name_match("Nobody Here", records) is None


def test_prominence_cache_recomputes_is_giant_with_run_thresholds(tmp_path):
    cache = Cache(str(tmp_path), enabled=True)
    # Seed the cache as if a *default*-threshold run wrote raw stats for an
    # author with 5000 citations / h-index 30 (not a giant by default).
    seed = Author(openalex_id="A9", name="Mid", cited_by_count=5000, h_index=30,
                  is_giant=False)
    cache.set("author", "A9", seed.to_dict())

    # A later run with a lower h-index threshold must see them as a giant,
    # recomputed from raw stats rather than the stale cached flag.
    out = authors.prominence(
        client=None, author_ids=["A9"], cache=cache,
        giant_cited_by=10000, giant_hindex=25,
    )
    assert out["A9"].is_giant is True
